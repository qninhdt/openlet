package temporal

import (
	"context"
	"strings"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
)

const (
	CreateStorageActivity             = "CreateStorage"
	CreateBucketActivity              = "CreateBucket"
	CreateFilesystemActivity          = "CreateFilesystem"
	ReleaseProvisioningActivity       = "ReleaseProvisioning"
	FreezeBucketActivity              = "FreezeBucket"
	ListBucketFilesystemsActivity     = "ListBucketFilesystems"
	CompleteBucketDeletionActivity    = "CompleteBucketDeletion"
	PrepareFilesystemDeletionActivity = "PrepareFilesystemDeletion"
)

// Caller authority comes from trusted owner workflows in the private namespace.
func storageContext(ctx context.Context, caller string) (context.Context, error) {
	if caller == "" || len(caller) > 64 || strings.TrimSpace(caller) != caller {
		return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "service authority required")
	}
	return identity.WithPrincipal(ctx, identity.Principal{Service: caller}), nil
}

func storageID(value string) (uuid.UUID, error) {
	id, err := uuid.Parse(value)
	if err != nil || id == uuid.Nil {
		return uuid.Nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid storage identity")
	}
	return id, nil
}

func (a *Activities) CreateBucket(ctx context.Context, caller string, input *letfsv1.CreateBucketRequest) (*letfsv1.Bucket, error) {
	ctx, err := storageContext(ctx, caller)
	if err != nil {
		return nil, activityError(err)
	}
	id, err := storageID(input.GetBucketId())
	if err != nil {
		return nil, activityError(err)
	}
	key, err := storageID(input.GetIdempotencyKey())
	if err != nil {
		return nil, activityError(err)
	}
	value, err := a.Store.CreateBucket(ctx, key, filesystem.CreateBucket{ID: id, LimitBytes: input.GetLimitBytes()})
	return bucketResult(value), activityError(err)
}

func (a *Activities) CreateFilesystem(ctx context.Context, caller string, input *letfsv1.CreateFilesystemRequest) (*letfsv1.Filesystem, error) {
	ctx, err := storageContext(ctx, caller)
	if err != nil {
		return nil, activityError(err)
	}
	id, err := storageID(input.GetFilesystemId())
	if err != nil {
		return nil, activityError(err)
	}
	bucket, err := storageID(input.GetBucketId())
	if err != nil {
		return nil, activityError(err)
	}
	key, err := storageID(input.GetIdempotencyKey())
	if err != nil {
		return nil, activityError(err)
	}
	value, err := a.Store.CreateFilesystem(ctx, key, filesystem.CreateFilesystem{ID: id, BucketID: bucket, RootName: input.GetRootName()})
	if err != nil {
		return nil, activityError(err)
	}
	root := ""
	if value.RootID != nil {
		root = value.RootID.String()
	}
	return &letfsv1.Filesystem{Id: value.ID.String(), BucketId: value.BucketID.String(), RootId: root, State: value.State}, nil
}

func (a *Activities) FreezeBucket(ctx context.Context, caller string, input *letfsv1.FreezeBucketRequest) (*letfsv1.Bucket, error) {
	ctx, err := storageContext(ctx, caller)
	if err != nil {
		return nil, activityError(err)
	}
	id, err := storageID(input.GetBucketId())
	if err != nil {
		return nil, activityError(err)
	}
	key, err := storageID(input.GetIdempotencyKey())
	if err != nil {
		return nil, activityError(err)
	}
	value, err := a.Store.FreezeBucket(ctx, key, id)
	return bucketResult(value), activityError(err)
}

func (a *Activities) ListBucketFilesystems(ctx context.Context, caller string, input *letfsv1.ListBucketFilesystemsRequest) (*letfsv1.ListBucketFilesystemsResponse, error) {
	ctx, err := storageContext(ctx, caller)
	if err != nil {
		return nil, activityError(err)
	}
	id, err := storageID(input.GetBucketId())
	if err != nil {
		return nil, activityError(err)
	}
	after := uuid.Nil
	if input.GetAfterId() != "" {
		after, err = storageID(input.GetAfterId())
		if err != nil {
			return nil, activityError(err)
		}
	}
	value, err := a.Store.ListBucketFilesystems(ctx, id, after)
	if err != nil {
		return nil, activityError(err)
	}
	result := &letfsv1.ListBucketFilesystemsResponse{FilesystemIds: make([]string, len(value))}
	for i, id := range value {
		result.FilesystemIds[i] = id.String()
	}
	return result, nil
}

func (a *Activities) ReleaseProvisioning(ctx context.Context, caller string, input *letfsv1.ReleaseProvisioningRequest) error {
	ctx, err := storageContext(ctx, caller)
	if err != nil {
		return activityError(err)
	}
	bucket, err := storageID(input.GetBucketId())
	if err != nil {
		return activityError(err)
	}
	fs, err := storageID(input.GetFilesystemId())
	if err != nil {
		return activityError(err)
	}
	root, err := storageID(input.GetRootId())
	if err != nil {
		return activityError(err)
	}
	return activityError(a.Store.ReleaseProvisioning(ctx, bucket, fs, root))
}

func (a *Activities) CompleteBucketDeletion(ctx context.Context, caller string, input *letfsv1.CompleteBucketDeletionRequest) (*letfsv1.Bucket, error) {
	ctx, err := storageContext(ctx, caller)
	if err != nil {
		return nil, activityError(err)
	}
	id, err := storageID(input.GetBucketId())
	if err != nil {
		return nil, activityError(err)
	}
	key, err := storageID(input.GetIdempotencyKey())
	if err != nil {
		return nil, activityError(err)
	}
	value, err := a.Store.CompleteBucketDeletion(ctx, key, id)
	return bucketResult(value), activityError(err)
}

func (a *Activities) PrepareFilesystemDeletion(ctx context.Context, caller string, fs uuid.UUID) error {
	ctx, err := storageContext(ctx, caller)
	if err != nil {
		return activityError(err)
	}
	return activityError(a.Store.PrepareFilesystemDeletion(ctx, fs))
}

func bucketResult(value filesystem.Bucket) *letfsv1.Bucket {
	return &letfsv1.Bucket{Id: value.ID.String(), LimitBytes: value.LimitBytes, UsedBytes: value.UsedBytes, State: value.State}
}

func (a *Activities) CreateStorage(ctx context.Context, caller string, input *letfsv1.CreateStorageRequest) (*letfsv1.CreateStorageResponse, error) {
	if input.GetBucket().GetBucketId() != input.GetFilesystem().GetBucketId() {
		return nil, activityError(rpc.Fault(codes.InvalidArgument, "VALIDATION", "storage scope mismatch"))
	}
	bucket, err := a.CreateBucket(ctx, caller, input.GetBucket())
	if err != nil {
		return nil, err
	}
	fs, err := a.CreateFilesystem(ctx, caller, input.GetFilesystem())
	if err != nil {
		return nil, err
	}
	return &letfsv1.CreateStorageResponse{Bucket: bucket, Filesystem: fs}, nil
}
