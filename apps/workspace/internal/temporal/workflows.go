package temporal

import (
	"context"
	"errors"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/letfs"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"strconv"
	"time"
)

const Queue = "openlet-workspace"

type Activities struct {
	Store    *workspace.Store
	Temporal client.Client
	Graph    v1.PermissionsServiceClient
}

func (a *Activities) SyncWorkspaceRelationships(ctx context.Context, id uuid.UUID) error {
	return businessError(a.Store.SyncRelationships(ctx, a.Graph, id))
}

func businessError(err error) error {
	var fault workspace.Fault
	if errors.As(err, &fault) {
		return temporal.NewNonRetryableApplicationError(fault.Code, fault.Code, err)
	}
	return err
}
func (a *Activities) EnsureWorkspace(ctx context.Context, in workspace.CreateInput) (uuid.UUID, error) {
	value, err := a.Store.EnsureWorkspace(ctx, in)
	return value.ID, businessError(err)
}
func (a *Activities) GetWorkspace(ctx context.Context, id uuid.UUID) (workspace.Workspace, error) {
	var value workspace.Workspace
	err := a.Store.DB.QueryRow(ctx, `SELECT id,status,quota_bucket_id,filesystem_id,root_id,limit_bytes::text FROM workspaces WHERE id=$1`, id).Scan(&value.ID, &value.Status, &value.BucketID, &value.FilesystemID, &value.RootID, &value.LimitBytes)
	return value, err
}
func (a *Activities) ActivateWorkspace(ctx context.Context, mapping workspace.Storage) error {
	return businessError(a.Store.Activate(ctx, mapping))
}
func (a *Activities) ReserveWorkspaceStorage(ctx context.Context, id uuid.UUID) (workspace.Storage, error) {
	value, err := a.Store.ReserveStorage(ctx, id)
	return value, businessError(err)
}
func (a *Activities) CompleteWorkspaceCreation(ctx context.Context, id uuid.UUID) error {
	return a.Store.CompleteCreation(ctx, id)
}
func (a *Activities) UnreleasedProvisioning(ctx context.Context) ([]workspace.Storage, error) {
	return a.Store.UnreleasedProvisioning(ctx)
}
func provisioned(mapping workspace.Storage) *letfsv1.ReleaseProvisioningRequest {
	return &letfsv1.ReleaseProvisioningRequest{BucketId: mapping.BucketID.String(), FilesystemId: mapping.FilesystemID.String(), RootId: mapping.RootID.String()}
}
func (a *Activities) FailWorkspace(ctx context.Context, id uuid.UUID) error {
	if err := a.Store.Fail(ctx, id); err != nil {
		return err
	}
	return a.SyncWorkspaceRelationships(ctx, id)
}
func CreateWorkspace(ctx workflow.Context, id uuid.UUID) (result uuid.UUID, err error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var a *Activities
	var value workspace.Workspace
	if err = workflow.ExecuteActivity(ctx, a.GetWorkspace, id).Get(ctx, &value); err != nil {
		return uuid.Nil, err
	}
	if value.Status == "deleted" || value.Status == "deleting" || value.Status == "failed" {
		return value.ID, temporal.NewNonRetryableApplicationError("workspace no longer provisioning", "STATE_CONFLICT", nil)
	}
	defer func() {
		if err != nil {
			disconnected, cancel := workflow.NewDisconnectedContext(ctx)
			defer cancel()
			_ = workflow.ExecuteActivity(disconnected, a.FailWorkspace, value.ID).Get(disconnected, nil)
		}
	}()
	if value.Status == "provisioning" {
		if err = workflow.ExecuteActivity(ctx, a.SyncWorkspaceRelationships, value.ID).Get(ctx, nil); err != nil {
			return value.ID, err
		}
	}
	remote := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{TaskQueue: letfs.Queue, StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var mapping workspace.Storage
	if value.Status == "active" {
		mapping = workspace.Storage{WorkspaceID: value.ID, BucketID: *value.BucketID, FilesystemID: *value.FilesystemID, RootID: *value.RootID, LimitBytes: value.LimitBytes}
	} else {
		if err = workflow.ExecuteActivity(ctx, a.ReserveWorkspaceStorage, value.ID).Get(ctx, &mapping); err != nil {
			return uuid.Nil, err
		}
		limit, parseErr := strconv.ParseInt(mapping.LimitBytes, 10, 64)
		if parseErr != nil || limit < 0 || mapping.WorkspaceID != value.ID || mapping.BucketID == uuid.Nil || mapping.FilesystemID == uuid.Nil {
			return value.ID, temporal.NewNonRetryableApplicationError("invalid reserved storage", "STORAGE_SCOPE_CONFLICT", parseErr)
		}
		var bucket *letfsv1.Bucket
		if err = workflow.ExecuteActivity(remote, letfs.CreateBucket, "workspace", &letfsv1.CreateBucketRequest{BucketId: mapping.BucketID.String(), IdempotencyKey: mapping.BucketID.String(), LimitBytes: limit}).Get(ctx, &bucket); err != nil {
			return value.ID, err
		}
		if bucket.GetId() != mapping.BucketID.String() || bucket.GetState() != "active" || bucket.GetLimitBytes() != limit {
			return uuid.Nil, temporal.NewNonRetryableApplicationError("invalid bucket result", "STORAGE_SCOPE_CONFLICT", nil)
		}
		var filesystem *letfsv1.Filesystem
		if err = workflow.ExecuteActivity(remote, letfs.CreateFilesystem, "workspace", &letfsv1.CreateFilesystemRequest{FilesystemId: mapping.FilesystemID.String(), BucketId: mapping.BucketID.String(), IdempotencyKey: mapping.FilesystemID.String(), RootName: "drive"}).Get(ctx, &filesystem); err != nil {
			return uuid.Nil, err
		}
		root, parseErr := uuid.Parse(filesystem.GetRootId())
		if parseErr != nil || root == uuid.Nil || filesystem.GetId() != mapping.FilesystemID.String() || filesystem.GetBucketId() != mapping.BucketID.String() || filesystem.GetState() != "active" {
			return uuid.Nil, temporal.NewNonRetryableApplicationError("invalid filesystem result", "STORAGE_SCOPE_CONFLICT", nil)
		}
		mapping.RootID = root
		if err = workflow.ExecuteActivity(ctx, a.ActivateWorkspace, mapping).Get(ctx, nil); err != nil {
			return uuid.Nil, err
		}
	}
	// Unpin only after the returned mapping is committed by its owner.
	if err = workflow.ExecuteActivity(remote, letfs.ReleaseProvisioning, "workspace", provisioned(mapping)).Get(ctx, nil); err != nil {
		return value.ID, err
	}
	if err = workflow.ExecuteActivity(ctx, a.SyncWorkspaceRelationships, value.ID).Get(ctx, nil); err != nil {
		return value.ID, err
	}
	err = workflow.ExecuteActivity(ctx, a.CompleteWorkspaceCreation, value.ID).Get(ctx, nil)
	return value.ID, err
}
func StartCreate(ctx context.Context, tc client.Client, id uuid.UUID) error {
	_, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "create-workspace/" + id.String(), TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, CreateWorkspace, id)
	return err
}
