package letfs

import (
	"bytes"
	"context"

	"github.com/google/uuid"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

type ScopePage struct {
	Items      []Scope
	NextCursor *string
}

func (c Client) ListScopes(ctx context.Context, fs uuid.UUID, limit int32, cursor *string) (ScopePage, error) {
	if fs == uuid.Nil || limit < 1 || limit > 100 || (cursor != nil && (len(*cursor) == 0 || len(*cursor) > 512)) {
		return ScopePage{}, scopeError()
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ListScopes(ctx, &letfsv1.ListScopesRequest{FilesystemId: fs.String(), Limit: &limit, Cursor: cursor})
	if err != nil {
		return ScopePage{}, rpc.DecodeError(err)
	}
	if response == nil || len(response.Scopes) > int(limit) {
		return ScopePage{}, scopeError()
	}
	result := ScopePage{Items: make([]Scope, len(response.Scopes)), NextCursor: response.NextCursor}
	previous := uuid.Nil
	seenRoots := map[uuid.UUID]bool{}
	for i, item := range response.Scopes {
		id, err := parseID(item.GetId())
		if err != nil || bytes.Compare(id[:], previous[:]) <= 0 || item.GetFilesystemId() != fs.String() || item.GetState() != "active" {
			return ScopePage{}, scopeError()
		}
		root, err := parseID(item.GetRootId())
		if err != nil || seenRoots[root] {
			return ScopePage{}, scopeError()
		}
		seenRoots[root] = true
		previous = id
		result.Items[i] = Scope{ID: id, FilesystemID: fs, RootID: root, State: "active", AllowBlobFiles: item.AllowBlobFiles, AllowIndexing: item.AllowIndexing}
	}
	if next := response.NextCursor; next != nil {
		if len(result.Items) == 0 || len(*next) == 0 || len(*next) > 512 || (cursor != nil && *next == *cursor) {
			return ScopePage{}, scopeError()
		}
	}
	return result, nil
}
