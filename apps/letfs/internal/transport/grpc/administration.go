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

func (s *Administration) CreateStorage(ctx context.Context, input *letfsv1.CreateStorageRequest) (*letfsv1.CreateStorageResponse, error) {
	if input.GetBucket() == nil || input.GetFilesystem() == nil || input.GetBucket().GetBucketId() != input.GetFilesystem().GetBucketId() {
		return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "storage scope mismatch")
	}
	bucketID, err := parseID(input.Bucket.GetBucketId())
	if err != nil {
		return nil, err
	}
	bucketKey, err := parseID(input.Bucket.GetIdempotencyKey())
	if err != nil {
		return nil, err
	}
	filesystemID, err := parseID(input.Filesystem.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	filesystemKey, err := parseID(input.Filesystem.GetIdempotencyKey())
	if err != nil {
		return nil, err
	}
	value, err := s.Service.CreateStorage(ctx, bucketKey, filesystem.CreateBucket{ID: bucketID, LimitBytes: input.Bucket.GetLimitBytes()}, filesystemKey,
		filesystem.CreateFilesystem{ID: filesystemID, BucketID: bucketID, RootName: input.Filesystem.GetRootName()})
	if err != nil {
		return nil, err
	}
	root := ""
	if value.Filesystem.RootID != nil {
		root = value.Filesystem.RootID.String()
	}
	return &letfsv1.CreateStorageResponse{Bucket: bucketMessage(value.Bucket), Filesystem: &letfsv1.Filesystem{
		Id: value.Filesystem.ID.String(), BucketId: value.Filesystem.BucketID.String(), RootId: root, State: value.Filesystem.State}}, nil
}

func (s *Administration) DeleteFilesystem(ctx context.Context, input *letfsv1.DeleteFilesystemRequest) (*letfsv1.DeleteFilesystemResponse, error) {
	id, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	completed, err := s.Service.DeleteFilesystem(ctx, id)
	if err != nil {
		return nil, err
	}
	return &letfsv1.DeleteFilesystemResponse{Completed: completed}, nil
}
