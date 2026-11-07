package grpc

import (
	"context"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
)

func (s *Filesystem) GetProcessing(ctx context.Context, input *letfsv1.GetProcessingRequest) (*letfsv1.GetProcessingResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetNodeId())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.GetProcessing(ctx, fs, id)
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetProcessingResponse{Processing: &letfsv1.Processing{FileId: value.FileID.String(), DesiredGeneration: value.DesiredGeneration,
		PublicationStatus: value.PublicationStatus, ErrorCode: value.ErrorCode}}, nil
}

func (s *Filesystem) ReprocessNode(ctx context.Context, input *letfsv1.ReprocessNodeRequest) (*letfsv1.ReprocessNodeResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetNodeId())
	if err != nil {
		return nil, err
	}
	key, err := parseID(input.GetIdempotencyKey())
	if err != nil {
		return nil, err
	}
	value, err := s.Service.Reprocess(ctx, fs, id, key)
	if err != nil {
		return nil, err
	}
	return &letfsv1.ReprocessNodeResponse{FileId: value.FileID.String(), Generation: value.Generation, WorkflowId: value.WorkflowID}, nil
}
