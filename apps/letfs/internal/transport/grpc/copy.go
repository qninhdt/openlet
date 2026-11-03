package grpc

import (
	"context"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
)

func copyMessage(state filesystem.CopyState) *letfsv1.Copy {
	return &letfsv1.Copy{Id: state.Admission.ID.String(), DestinationRootId: state.Admission.Root.Destination.String(),
		Status: state.Status, CommittedNodes: state.CommittedNodes, CommittedBytes: state.CommittedBytes, ErrorCode: state.ErrorCode}
}

func (s *Filesystem) CreateCopy(ctx context.Context, input *letfsv1.CreateCopyRequest) (*letfsv1.CreateCopyResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
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
	mounts, err := pathInput(input.GetPathContext())
	if err != nil {
		return nil, err
	}
	state, err := s.Service.CreateCopy(ctx, fs, mounts, key, filesystem.CreateCopy{SourceID: source, ParentID: parent, Name: input.GetName(), Revision: input.Revision})
	if err != nil {
		return nil, err
	}
	result := copyMessage(state)
	return &letfsv1.CreateCopyResponse{Copy: result}, nil
}

func (s *Filesystem) GetCopy(ctx context.Context, input *letfsv1.GetCopyRequest) (*letfsv1.GetCopyResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetCopyId())
	if err != nil {
		return nil, err
	}
	state, err := s.Service.GetCopy(ctx, fs, id)
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetCopyResponse{Copy: copyMessage(state)}, nil
}
