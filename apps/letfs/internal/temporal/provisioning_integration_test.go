//go:build integration

package temporal

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/client"
	sdktemporal "go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

func provisionRoundtrip(ctx workflow.Context, bucket, fs, key uuid.UUID) (*letfsv1.Bucket, error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 10 * time.Second})
	input := &letfsv1.CreateBucketRequest{BucketId: bucket.String(), IdempotencyKey: key.String(), LimitBytes: 1000}
	var created *letfsv1.Bucket
	if err := workflow.ExecuteActivity(ctx, CreateBucketActivity, "resource-owner", input).Get(ctx, &created); err != nil {
		return created, err
	}
	if err := workflow.ExecuteActivity(ctx, CreateBucketActivity, "resource-owner", input).Get(ctx, &created); err != nil {
		return created, err
	}
	var response *letfsv1.CreateStorageResponse
	request := &letfsv1.CreateStorageRequest{Bucket: input, Filesystem: &letfsv1.CreateFilesystemRequest{FilesystemId: fs.String(), BucketId: bucket.String(), IdempotencyKey: key.String(), RootName: "files"}}
	for range 2 {
		if err := workflow.ExecuteActivity(ctx, CreateStorageActivity, "resource-owner", request).Get(ctx, &response); err != nil {
			return created, err
		}
	}
	storage := response.Filesystem
	if err := workflow.ExecuteActivity(ctx, ReleaseProvisioningActivity, "resource-owner", &letfsv1.ReleaseProvisioningRequest{
		BucketId: bucket.String(), FilesystemId: fs.String(), RootId: storage.RootId}).Get(ctx, nil); err != nil {
		return created, err
	}
	if err := workflow.ExecuteActivity(ctx, FreezeBucketActivity, "other-owner", &letfsv1.FreezeBucketRequest{BucketId: bucket.String(), IdempotencyKey: key.String()}).Get(ctx, nil); err != nil {
		return created, err
	}
	if err := workflow.ExecuteActivity(ctx, FreezeBucketActivity, "resource-owner", &letfsv1.FreezeBucketRequest{BucketId: bucket.String(), IdempotencyKey: key.String()}).Get(ctx, nil); err != nil {
		return created, err
	}
	var ids *letfsv1.ListBucketFilesystemsResponse
	if err := workflow.ExecuteActivity(ctx, ListBucketFilesystemsActivity, "resource-owner", &letfsv1.ListBucketFilesystemsRequest{BucketId: bucket.String()}).Get(ctx, &ids); err != nil {
		return created, err
	}
	if len(ids.FilesystemIds) != 1 || ids.FilesystemIds[0] != fs.String() {
		return created, sdktemporal.NewNonRetryableApplicationError("unexpected storage list", "TEST_FAILURE", nil)
	}
	if err := workflow.ExecuteActivity(ctx, PrepareFilesystemDeletionActivity, "resource-owner", fs).Get(ctx, nil); err != nil {
		return created, err
	}
	child := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{WorkflowID: "delete-filesystem/" + fs.String(), TaskQueue: Queue, WorkflowExecutionTimeout: 7 * 24 * time.Hour})
	if err := workflow.ExecuteChildWorkflow(child, DeleteFilesystemName, DeletionInput{FilesystemID: fs}).Get(ctx, nil); err != nil {
		return created, err
	}
	err := workflow.ExecuteActivity(ctx, CompleteBucketDeletionActivity, "resource-owner", &letfsv1.CompleteBucketDeletionRequest{BucketId: bucket.String(), IdempotencyKey: key.String()}).Get(ctx, &created)
	return created, err
}

func TestIntegrationGenericProvisioningActivities(t *testing.T) {
	tc, _ := testfixture.Temporal(t)
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	w := worker.New(tc, Queue, worker.Options{WorkerStopTimeout: time.Second})
	Register(w, &Activities{Store: &filesystem.Store{DB: db, MaxNodes: 100}})
	w.RegisterWorkflow(provisionRoundtrip)
	require.NoError(t, w.Start())
	t.Cleanup(w.Stop)
	ctx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
	defer cancel()
	bucket, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	run, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "generic-provision/" + fs.String(), TaskQueue: Queue}, provisionRoundtrip, bucket, fs, uuid.New())
	require.NoError(t, err)
	var result *letfsv1.Bucket
	require.NoError(t, run.Get(ctx, &result))
	require.Equal(t, bucket.String(), result.Id)
	require.Equal(t, "deleted", result.State)
	require.Zero(t, result.UsedBytes)
	var buckets, filesystems int
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM quota_buckets`).Scan(&buckets))
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM filesystems`).Scan(&filesystems))
	require.Equal(t, 1, buckets)
	require.Equal(t, 1, filesystems)
}
