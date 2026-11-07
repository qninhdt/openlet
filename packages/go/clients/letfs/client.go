package letfs

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

type Client struct {
	API letfsv1.StorageAdministrationServiceClient
}

func scopeError() error {
	return apperr.New(apperr.Conflict, "STORAGE_SCOPE_CONFLICT", "invalid storage result")
}
func bounded(ctx context.Context) (context.Context, context.CancelFunc) {
	return context.WithTimeout(ctx, 10*time.Second)
}

func uuidString(id *uuid.UUID) *string {
	if id == nil {
		return nil
	}
	value := id.String()
	return &value
}
func (c Client) CreateFilesystem(ctx context.Context, id, key uuid.UUID, limit int64) (Filesystem, error) {
	if id == uuid.Nil || key == uuid.Nil || limit < 0 {
		return Filesystem{}, scopeError()
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CreateFilesystem(ctx, &letfsv1.CreateFilesystemRequest{FilesystemId: id.String(), IdempotencyKey: key.String(), LimitBytes: limit})
	if err != nil {
		return Filesystem{}, rpc.DecodeError(err)
	}
	value, err := nativeFilesystem(response.GetFilesystem())
	if err != nil || value.ID != id || value.LimitBytes != limit {
		return Filesystem{}, scopeError()
	}
	return value, nil
}

type Scope struct {
	ID, FilesystemID, RootID      uuid.UUID
	State                         string
	AllowBlobFiles, AllowIndexing bool
}

func (c Client) CreateScopes(ctx context.Context, fs, key uuid.UUID, ids []uuid.UUID, allowBlobFiles, allowIndexing bool) ([]Scope, error) {
	if fs == uuid.Nil || key == uuid.Nil || len(ids) == 0 || len(ids) > 100 {
		return nil, scopeError()
	}
	values := make([]string, len(ids))
	seen := map[uuid.UUID]bool{}
	for i, id := range ids {
		if id == uuid.Nil || seen[id] {
			return nil, scopeError()
		}
		values[i] = id.String()
		seen[id] = true
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CreateScopes(ctx, &letfsv1.CreateScopesRequest{FilesystemId: fs.String(), IdempotencyKey: key.String(), ScopeIds: values, AllowBlobFiles: &allowBlobFiles, AllowIndexing: &allowIndexing})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	if len(response.GetScopes()) != len(ids) {
		return nil, scopeError()
	}
	result := make([]Scope, len(ids))
	for i, value := range response.Scopes {
		id, err := parseID(value.GetId())
		if err != nil || !seen[id] || value.GetFilesystemId() != fs.String() || value.GetAllowBlobFiles() != allowBlobFiles || value.GetAllowIndexing() != allowIndexing {
			return nil, scopeError()
		}
		delete(seen, id)
		root, err := parseID(value.GetRootId())
		if err != nil {
			return nil, err
		}
		result[i] = Scope{ID: id, FilesystemID: fs, RootID: root, State: value.State, AllowBlobFiles: value.AllowBlobFiles, AllowIndexing: value.AllowIndexing}
	}
	return result, nil
}
func (c Client) DeleteFilesystem(ctx context.Context, id uuid.UUID) (bool, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.DeleteFilesystem(ctx, &letfsv1.DeleteFilesystemRequest{FilesystemId: id.String()})
	if err != nil {
		return false, rpc.DecodeError(err)
	}
	return response.GetCompleted(), nil
}
