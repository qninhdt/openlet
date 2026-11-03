package letfs

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

type Storage struct {
	LimitBytes   int64
	BucketID     uuid.UUID
	FilesystemID uuid.UUID
	RootID       uuid.UUID
}
type Bucket struct {
	ID                    uuid.UUID
	LimitBytes, UsedBytes int64
	State                 string
}

type Client struct {
	API letfsv1.StorageAdministrationServiceClient
}

func scopeError() error {
	return apperr.New(apperr.Conflict, "STORAGE_SCOPE_CONFLICT", "invalid storage result")
}

func bounded(ctx context.Context) (context.Context, context.CancelFunc) {
	return context.WithTimeout(ctx, 10*time.Second)
}

func (c Client) CreateStorage(ctx context.Context, value Storage) (Storage, error) {
	if value.LimitBytes < 0 || value.BucketID == uuid.Nil || value.FilesystemID == uuid.Nil {
		return value, scopeError()
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CreateStorage(ctx, &letfsv1.CreateStorageRequest{
		Bucket:     &letfsv1.CreateBucketRequest{BucketId: value.BucketID.String(), IdempotencyKey: value.BucketID.String(), LimitBytes: value.LimitBytes},
		Filesystem: &letfsv1.CreateFilesystemRequest{FilesystemId: value.FilesystemID.String(), BucketId: value.BucketID.String(), IdempotencyKey: value.FilesystemID.String(), RootName: "drive"},
	})
	if err != nil {
		return value, rpc.DecodeError(err)
	}
	bucket, filesystem := response.GetBucket(), response.GetFilesystem()
	root, err := uuid.Parse(filesystem.GetRootId())
	if err != nil || root == uuid.Nil || filesystem.GetId() != value.FilesystemID.String() || filesystem.GetBucketId() != value.BucketID.String() || filesystem.GetState() != "active" || bucket.GetId() != value.BucketID.String() || bucket.GetState() != "active" || bucket.GetLimitBytes() != value.LimitBytes {
		return value, scopeError()
	}
	value.RootID = root
	return value, nil
}
func (c Client) CreateBucket(ctx context.Context, id, key uuid.UUID, limit int64) (Bucket, error) {
	if id == uuid.Nil || key == uuid.Nil || limit < 0 {
		return Bucket{}, scopeError()
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CreateBucket(ctx, &letfsv1.CreateBucketRequest{BucketId: id.String(), IdempotencyKey: key.String(), LimitBytes: limit})
	if err != nil {
		return Bucket{}, rpc.DecodeError(err)
	}
	value := response.GetBucket()
	parsed, err := parseID(value.GetId())
	if err != nil || parsed != id || value.GetLimitBytes() != limit {
		return Bucket{}, scopeError()
	}
	return Bucket{ID: parsed, LimitBytes: value.GetLimitBytes(), UsedBytes: value.GetUsedBytes(), State: value.GetState()}, nil
}
func (c Client) CreateFilesystem(ctx context.Context, id, bucket, key uuid.UUID, rootName string) (Filesystem, error) {
	if id == uuid.Nil || bucket == uuid.Nil || key == uuid.Nil {
		return Filesystem{}, scopeError()
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CreateFilesystem(ctx, &letfsv1.CreateFilesystemRequest{FilesystemId: id.String(), BucketId: bucket.String(), IdempotencyKey: key.String(), RootName: rootName})
	if err != nil {
		return Filesystem{}, rpc.DecodeError(err)
	}
	value, err := nativeFilesystem(response.GetFilesystem())
	if err != nil || value.ID != id || value.BucketID != bucket {
		return Filesystem{}, scopeError()
	}
	return value, nil
}

func (c Client) ReleaseProvisioning(ctx context.Context, value Storage) error {
	ctx, cancel := bounded(ctx)
	defer cancel()
	_, err := c.API.ReleaseProvisioning(ctx, &letfsv1.ReleaseProvisioningRequest{BucketId: value.BucketID.String(), FilesystemId: value.FilesystemID.String(), RootId: value.RootID.String()})
	return rpc.DecodeError(err)
}

func (c Client) FreezeBucket(ctx context.Context, id uuid.UUID) error {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.FreezeBucket(ctx, &letfsv1.FreezeBucketRequest{BucketId: id.String(), IdempotencyKey: id.String()})
	if err != nil {
		return rpc.DecodeError(err)
	}
	bucket := response.GetBucket()
	if bucket.GetId() != id.String() || bucket.GetState() != "frozen" && bucket.GetState() != "deleted" {
		return scopeError()
	}
	return nil
}

func (c Client) ListFilesystems(ctx context.Context, bucket, after uuid.UUID) ([]uuid.UUID, error) {
	request := &letfsv1.ListBucketFilesystemsRequest{BucketId: bucket.String()}
	if after != uuid.Nil {
		cursor := after.String()
		request.AfterId = &cursor
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ListBucketFilesystems(ctx, request)
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	if len(response.GetFilesystemIds()) > 100 {
		return nil, scopeError()
	}
	ids := make([]uuid.UUID, 0, len(response.GetFilesystemIds()))
	previous := after
	for _, raw := range response.GetFilesystemIds() {
		id, err := uuid.Parse(raw)
		if err != nil || id == uuid.Nil || id.String() <= previous.String() {
			return nil, scopeError()
		}
		ids, previous = append(ids, id), id
	}
	return ids, nil
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

func (c Client) CompleteBucket(ctx context.Context, id uuid.UUID) error {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CompleteBucketDeletion(ctx, &letfsv1.CompleteBucketDeletionRequest{BucketId: id.String(), IdempotencyKey: id.String()})
	if err != nil {
		return rpc.DecodeError(err)
	}
	bucket := response.GetBucket()
	if bucket.GetId() != id.String() || bucket.GetState() != "deleted" {
		return scopeError()
	}
	return nil
}
