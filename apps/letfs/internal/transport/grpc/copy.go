package grpc

import (
	"context"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
)

func copyMessage(value filesystem.CopyResult) *letfsv1.Copy {
	return &letfsv1.Copy{Id: value.ID.String(), DestinationRootId: value.DestinationRootID.String()}
}

func (s *Filesystem) CreateCopy(ctx context.Context, input *letfsv1.CreateCopyRequest) (*letfsv1.CreateCopyResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	source, err := parseID(input.GetSourceId())
	if err != nil {
		return nil, err
	}
	parent, err := parseID(input.GetParentId())
	if err != nil {
		return nil, err
	}
	key, err := parseID(input.GetIdempotencyKey())
	if err != nil {
		return nil, err
	}
	destination, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetDestinationScopeId())
	if err != nil {
		return nil, err
	}
	state, err := s.Service.CreateCopy(ctx, fs, key, filesystem.CreateCopy{DestinationScopeID: destination, SourceID: source, ParentID: parent, Name: input.GetName(), Revision: input.Revision})
	if err != nil {
		return nil, err
	}
	result := copyMessage(state)
	return &letfsv1.CreateCopyResponse{Copy: result}, nil
}
