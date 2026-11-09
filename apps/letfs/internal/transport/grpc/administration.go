package grpc

import (
	"context"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
)

type Administration struct {
	letfsv1.UnimplementedStorageAdministrationServiceServer
	Store   *filesystem.Store
	Service *filesystem.Service
}

func parseID(value string) (uuid.UUID, error) {
	id, err := uuid.Parse(value)
	if err != nil || id == uuid.Nil {
		return uuid.Nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid UUID")
	}
	return id, nil
}

func filesystemMessage(value filesystem.Filesystem) *letfsv1.Filesystem {
	return &letfsv1.Filesystem{Id: value.ID.String(), LimitBytes: value.LimitBytes, UsedBytes: value.UsedBytes, NodeCount: value.NodeCount, State: value.State}
}
func (s *Administration) CreateFilesystem(ctx context.Context, input *letfsv1.CreateFilesystemRequest) (*letfsv1.CreateFilesystemResponse, error) {
	id, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	key, err := parseID(input.GetIdempotencyKey())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.CreateFilesystem(ctx, key, filesystem.CreateFilesystem{ID: id, LimitBytes: input.LimitBytes})
	if err != nil {
		return nil, err
	}
	return &letfsv1.CreateFilesystemResponse{Filesystem: filesystemMessage(value)}, nil
}
func (s *Administration) CreateScopes(ctx context.Context, input *letfsv1.CreateScopesRequest) (*letfsv1.CreateScopesResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	key, err := parseID(input.GetIdempotencyKey())
	if err != nil {
		return nil, err
	}
	ids := make([]uuid.UUID, len(input.ScopeIds))
	for i, value := range input.ScopeIds {
		ids[i], err = parseID(value)
		if err != nil {
			return nil, err
		}
	}
	values, err := s.Store.CreateScopes(ctx, key, fs, ids, input.AllowBlobFiles == nil || input.GetAllowBlobFiles(), input.AllowIndexing == nil || input.GetAllowIndexing())
	if err != nil {
		return nil, err
	}
	result := &letfsv1.CreateScopesResponse{Scopes: make([]*letfsv1.Scope, len(values))}
	for i, value := range values {
		result.Scopes[i] = &letfsv1.Scope{Id: value.ID.String(), FilesystemId: fs.String(), RootId: value.RootID.String(), State: value.State, AllowBlobFiles: value.AllowBlobFiles, AllowIndexing: value.AllowIndexing}
	}
	return result, nil
}
func (s *Administration) DeleteFilesystem(ctx context.Context, input *letfsv1.DeleteFilesystemRequest) (*letfsv1.DeleteFilesystemResponse, error) {
	id, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	completed, err := s.Service.DeleteFilesystem(ctx, id)
	return &letfsv1.DeleteFilesystemResponse{Completed: completed}, err
}

func (s *Administration) ListScopes(ctx context.Context, input *letfsv1.ListScopesRequest) (*letfsv1.ListScopesResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	page, err := s.Store.ListScopes(ctx, fs, input.Cursor, input.Limit)
	if err != nil {
		return nil, err
	}
	result := &letfsv1.ListScopesResponse{Scopes: make([]*letfsv1.Scope, len(page.Items)), NextCursor: page.NextCursor}
	for i, scope := range page.Items {
		result.Scopes[i] = &letfsv1.Scope{Id: scope.ID.String(), FilesystemId: scope.FilesystemID.String(), RootId: scope.RootID.String(), State: scope.State, AllowBlobFiles: scope.AllowBlobFiles, AllowIndexing: scope.AllowIndexing}
	}
	return result, nil
}
