package grpc

import (
	"context"

	"github.com/google/uuid"
	"google.golang.org/grpc/codes"
	"openlet/apps/letfs/internal/filesystem"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/rpc"
)

type Administration struct {
	letfsv1.UnimplementedStorageAdministrationServiceServer
	Store *filesystem.Store
}

func parseID(value string) (uuid.UUID, error) {
	id, err := uuid.Parse(value)
	if err != nil || id == uuid.Nil {
		return uuid.Nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid UUID")
	}
	return id, nil
}

func bucketMessage(value filesystem.Bucket) *letfsv1.Bucket {
	return &letfsv1.Bucket{Id: value.ID.String(), LimitBytes: value.LimitBytes, UsedBytes: value.UsedBytes, State: value.State}
}

func (s *Administration) CreateBucket(ctx context.Context, input *letfsv1.CreateBucketRequest) (*letfsv1.CreateBucketResponse, error) {
	id, err := parseID(input.BucketId)
	if err != nil {
		return nil, err
	}
	key, err := parseID(input.IdempotencyKey)
	if err != nil {
		return nil, err
	}
	value, err := s.Store.CreateBucket(ctx, key, filesystem.CreateBucket{ID: id, LimitBytes: input.LimitBytes})
	if err != nil {
		return nil, err
	}
	return &letfsv1.CreateBucketResponse{Bucket: bucketMessage(value)}, nil
}

func (s *Administration) CreateFilesystem(ctx context.Context, input *letfsv1.CreateFilesystemRequest) (*letfsv1.CreateFilesystemResponse, error) {
	id, err := parseID(input.FilesystemId)
	if err != nil {
		return nil, err
	}
	bucket, err := parseID(input.BucketId)
	if err != nil {
		return nil, err
	}
	key, err := parseID(input.IdempotencyKey)
	if err != nil {
		return nil, err
	}
	value, err := s.Store.CreateFilesystem(ctx, key, filesystem.CreateFilesystem{ID: id, BucketID: bucket, RootName: input.RootName})
	if err != nil {
		return nil, err
	}
	root := ""
	if value.RootID != nil {
		root = value.RootID.String()
	}
	return &letfsv1.CreateFilesystemResponse{Filesystem: &letfsv1.Filesystem{Id: value.ID.String(), BucketId: value.BucketID.String(), RootId: root, State: value.State}}, nil
}

func (s *Administration) FreezeBucket(ctx context.Context, input *letfsv1.FreezeBucketRequest) (*letfsv1.FreezeBucketResponse, error) {
	id, err := parseID(input.BucketId)
	if err != nil {
		return nil, err
	}
	key, err := parseID(input.IdempotencyKey)
	if err != nil {
		return nil, err
	}
	value, err := s.Store.FreezeBucket(ctx, key, id)
	if err != nil {
		return nil, err
	}
	return &letfsv1.FreezeBucketResponse{Bucket: bucketMessage(value)}, nil
}

func (s *Administration) ListBucketFilesystems(ctx context.Context, input *letfsv1.ListBucketFilesystemsRequest) (*letfsv1.ListBucketFilesystemsResponse, error) {
	id, err := parseID(input.BucketId)
	if err != nil {
		return nil, err
	}
	after := uuid.Nil
	if input.AfterId != nil {
		after, err = parseID(*input.AfterId)
		if err != nil {
			return nil, err
		}
	}
	ids, err := s.Store.ListBucketFilesystems(ctx, id, after)
	if err != nil {
		return nil, err
	}
	result := &letfsv1.ListBucketFilesystemsResponse{FilesystemIds: make([]string, len(ids))}
	for i, id := range ids {
		result.FilesystemIds[i] = id.String()
	}
	return result, nil
}

func (s *Administration) CompleteBucketDeletion(ctx context.Context, input *letfsv1.CompleteBucketDeletionRequest) (*letfsv1.CompleteBucketDeletionResponse, error) {
	id, err := parseID(input.BucketId)
	if err != nil {
		return nil, err
	}
	key, err := parseID(input.IdempotencyKey)
	if err != nil {
		return nil, err
	}
	value, err := s.Store.CompleteBucketDeletion(ctx, key, id)
	if err != nil {
		return nil, err
	}
	return &letfsv1.CompleteBucketDeletionResponse{Bucket: bucketMessage(value)}, nil
}

func (s *Administration) ReleaseProvisioning(ctx context.Context, input *letfsv1.ReleaseProvisioningRequest) (*letfsv1.ReleaseProvisioningResponse, error) {
	bucket, err := parseID(input.BucketId)
	if err != nil {
		return nil, err
	}
	fs, err := parseID(input.FilesystemId)
	if err != nil {
		return nil, err
	}
	root, err := parseID(input.RootId)
	if err != nil {
		return nil, err
	}
	if err = s.Store.ReleaseProvisioning(ctx, bucket, fs, root); err != nil {
		return nil, err
	}
	return &letfsv1.ReleaseProvisioningResponse{}, nil
}
