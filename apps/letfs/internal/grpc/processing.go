package grpc

import (
	"context"
	"log/slog"

	"github.com/google/uuid"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
)

func (s *Filesystem) dispatchPending(ctx context.Context, file uuid.UUID) {
	if s.Jobs == nil {
		return
	}
	dispatch, err := s.Store.PendingProcessing(ctx, file)
	if err == nil {
		err = s.Jobs.StartProcessing(ctx, dispatch)
	}
	if err != nil {
		slog.WarnContext(ctx, "processing dispatch deferred")
	}
}

func (s *Filesystem) GetProcessing(ctx context.Context, input *letfsv1.GetProcessingRequest) (*letfsv1.GetProcessingResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetNodeId())
	if err != nil {
		return nil, err
	}
	mounts, err := pathInput(input.GetPathContext())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.GetProcessing(ctx, fs, mounts, id)
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetProcessingResponse{Processing: &letfsv1.Processing{FileId: value.FileID.String(), DesiredGeneration: value.DesiredGeneration,
		PublicationStatus: value.PublicationStatus, ErrorCode: value.ErrorCode}}, nil
}

func (s *Filesystem) ReprocessNode(ctx context.Context, input *letfsv1.ReprocessNodeRequest) (*letfsv1.ReprocessNodeResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
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
	mounts, err := pathInput(input.GetPathContext())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.Reprocess(ctx, fs, mounts, id, key)
	if err != nil {
		return nil, err
	}
	s.dispatchPending(ctx, value.FileID)
	return &letfsv1.ReprocessNodeResponse{FileId: value.FileID.String(), Generation: value.Generation, WorkflowId: value.WorkflowID}, nil
}
