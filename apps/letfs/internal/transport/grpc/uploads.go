package grpc

import (
	"context"

	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func signedUploadMessage(value storage.SignedUpload) *letfsv1.SignedUpload {
	return &letfsv1.SignedUpload{Url: value.URL, Headers: value.Headers, ContentLength: value.ContentLength, ExpiresAt: timestamppb.New(value.ExpiresAt)}
}

func publicationMessage(value filesystem.UploadPublication) *letfsv1.UploadPublication {
	return &letfsv1.UploadPublication{NodeId: value.NodeID.String(), Status: value.Status, Revision: value.Revision}
}

func uploadMessage(value filesystem.Upload) *letfsv1.Upload {
	result := &letfsv1.Upload{Id: value.ID.String(), Status: value.State, Transport: value.Transport, ExpiresAt: timestamppb.New(value.ExpiresAt), SizeBytes: &value.SizeBytes, PartSizeBytes: value.PartSize}
	if value.PartSize != nil {
		count := value.PartCount()
		result.PartCount = &count
	}
	if value.Transfer != nil {
		result.Transfer = signedUploadMessage(*value.Transfer)
	}
	if value.Publication != nil {
		result.Result = &letfsv1.Upload_Publication{Publication: publicationMessage(*value.Publication)}
	}
	return result
}

func (s *Filesystem) CreateUpload(ctx context.Context, input *letfsv1.CreateUploadRequest) (*letfsv1.CreateUploadResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	key, err := parseID(input.GetIdempotencyKey())
	if err != nil {
		return nil, err
	}
	creation := filesystem.UploadCreation{SizeBytes: input.SizeBytes, MediaType: input.GetMediaType(), ContentMD5: input.ContentMd5}
	switch target := input.GetTarget().(type) {
	case *letfsv1.CreateUploadRequest_Destination:
		if target.Destination == nil {
			return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "destination required")
		}
		parent, err := locatorInput(target.Destination.Parent)
		if err != nil {
			return nil, err
		}
		creation.Destination = &filesystem.UploadDestination{Parent: parent, Name: target.Destination.Name}
	case *letfsv1.CreateUploadRequest_Replacement:
		if target.Replacement == nil {
			return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "replacement required")
		}
		locator, err := locatorInput(target.Replacement.Locator)
		if err != nil {
			return nil, err
		}
		creation.Replacement = &filesystem.UploadReplacement{Locator: locator, Revision: target.Replacement.Revision}
	default:
		return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "upload target required")
	}
	value, err := s.Service.CreateUpload(ctx, fs, key, creation)
	if err != nil {
		return nil, err
	}
	return &letfsv1.CreateUploadResponse{Upload: uploadMessage(value)}, nil
}

func (s *Filesystem) GetUpload(ctx context.Context, input *letfsv1.GetUploadRequest) (*letfsv1.GetUploadResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetUploadId())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.GetUpload(ctx, fs, id)
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetUploadResponse{Upload: uploadMessage(value)}, nil
}

func (s *Filesystem) GetUploadParts(ctx context.Context, input *letfsv1.GetUploadPartsRequest) (*letfsv1.GetUploadPartsResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetUploadId())
	if err != nil {
		return nil, err
	}
	values, err := s.Store.GetUploadParts(ctx, fs, id, input.GetNumbers())
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetUploadPartsResponse{Items: uploadPartsMessage(values)}, nil
}

func uploadPartsMessage(values []filesystem.UploadPart) []*letfsv1.UploadPart {
	result := make([]*letfsv1.UploadPart, len(values))
	for i, value := range values {
		result[i] = &letfsv1.UploadPart{PartNumber: value.Number, Transfer: signedUploadMessage(value.Transfer)}
	}
	return result
}

func (s *Filesystem) CompleteUpload(ctx context.Context, input *letfsv1.CompleteUploadRequest) (*letfsv1.CompleteUploadResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetUploadId())
	if err != nil {
		return nil, err
	}
	parts, err := partReceiptsInput(input.Parts)
	if err != nil {
		return nil, err
	}
	value, err := s.Service.CompleteUpload(ctx, fs, id, parts)
	if err != nil {
		return nil, err
	}
	return &letfsv1.CompleteUploadResponse{Publication: publicationMessage(value)}, nil
}

func (s *Filesystem) AbortUpload(ctx context.Context, input *letfsv1.AbortUploadRequest) (*letfsv1.AbortUploadResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetUploadId())
	if err != nil {
		return nil, err
	}
	if err = s.Service.AbortUpload(ctx, fs, id); err != nil {
		return nil, err
	}
	return &letfsv1.AbortUploadResponse{}, nil
}

func partReceiptsInput(input []*letfsv1.PartReceipt) ([]storage.PartReceipt, error) {
	if len(input) > 10000 {
		return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "at most 10000 part receipts allowed")
	}
	parts := make([]storage.PartReceipt, len(input))
	for i, part := range input {
		if part == nil {
			return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "part receipt required")
		}
		parts[i] = storage.PartReceipt{Number: part.PartNumber, ETag: part.Etag}
	}
	return parts, nil
}
