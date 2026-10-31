package temporal

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"openlet/apps/workspace/internal/letfs"
	"openlet/apps/workspace/internal/workspace"
	"time"
)

const Queue = "openlet-workspace"

type Activities struct {
	Store    *workspace.Store
	Temporal client.Client
}

func businessError(err error) error {
	var fault workspace.Fault
	if errors.As(err, &fault) {
		return temporal.NewNonRetryableApplicationError(fault.Code, fault.Code, err)
	}
	return err
}
func (a *Activities) EnsureWorkspace(ctx context.Context, in workspace.CreateInput) (workspace.Provision, error) {
	value, err := a.Store.EnsureWorkspace(ctx, in, activity.GetInfo(ctx).WorkflowExecution.ID)
	return value, businessError(err)
}
func (a *Activities) ActivateWorkspace(ctx context.Context, mapping workspace.Storage) error {
	return businessError(a.Store.Activate(ctx, mapping))
}
func (a *Activities) CompleteWorkspaceCreation(ctx context.Context, id uuid.UUID) error {
	return a.Store.CompleteCreation(ctx, id)
}
func (a *Activities) UnreleasedProvisioning(ctx context.Context) ([]workspace.Storage, error) {
	return a.Store.UnreleasedProvisioning(ctx)
}
func provisioned(mapping workspace.Storage) letfs.Provisioned {
	return letfs.Provisioned{BucketScope: letfs.BucketScope{WorkspaceID: mapping.WorkspaceID, BucketID: mapping.BucketID}, FilesystemID: mapping.FilesystemID, RootID: mapping.RootID}
}
func (a *Activities) FailWorkspace(ctx context.Context, id uuid.UUID) error {
	return a.Store.Fail(ctx, id)
}
func CreateWorkspace(ctx workflow.Context, in workspace.CreateInput) (result uuid.UUID, err error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var a *Activities
	var admission workspace.Provision
	if err = workflow.ExecuteActivity(ctx, a.EnsureWorkspace, in).Get(ctx, &admission); err != nil {
		return uuid.Nil, err
	}
	value := admission.Workspace
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
	remote := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{TaskQueue: letfs.Queue, StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var mapping workspace.Storage
	if value.Status == "active" {
		mapping = workspace.Storage{WorkspaceID: value.ID, BucketID: *value.BucketID, FilesystemID: *value.FilesystemID, RootID: *value.RootID, LimitBytes: value.LimitBytes}
	} else {
		var bucket letfs.Bucket
		if err = workflow.ExecuteActivity(remote, letfs.ProvisionBucket, letfs.BucketInput{WorkspaceID: value.ID, LimitBytes: value.LimitBytes}).Get(ctx, &bucket); err != nil {
			return uuid.Nil, err
		}
		if bucket.ID == uuid.Nil || bucket.State != "active" || bucket.LimitBytes != value.LimitBytes {
			return uuid.Nil, temporal.NewNonRetryableApplicationError("invalid bucket result", "STORAGE_SCOPE_CONFLICT", nil)
		}
		var filesystem letfs.Filesystem
		if err = workflow.ExecuteActivity(remote, letfs.ProvisionFilesystem, letfs.FilesystemInput{WorkspaceID: value.ID, BucketID: bucket.ID}).Get(ctx, &filesystem); err != nil {
			return uuid.Nil, err
		}
		if filesystem.ID == uuid.Nil || filesystem.RootID == uuid.Nil || filesystem.BucketID != bucket.ID || filesystem.State != "active" {
			return uuid.Nil, temporal.NewNonRetryableApplicationError("invalid filesystem result", "STORAGE_SCOPE_CONFLICT", nil)
		}
		mapping = workspace.Storage{WorkspaceID: value.ID, BucketID: bucket.ID, FilesystemID: filesystem.ID, RootID: filesystem.RootID, LimitBytes: value.LimitBytes}
		if err = workflow.ExecuteActivity(ctx, a.ActivateWorkspace, mapping).Get(ctx, nil); err != nil {
			return uuid.Nil, err
		}
	}
	// Unpin only after the returned mapping is committed by its owner.
	if err = workflow.ExecuteActivity(remote, letfs.ReleaseProvisioning, provisioned(mapping)).Get(ctx, nil); err != nil {
		return value.ID, err
	}
	err = workflow.ExecuteActivity(ctx, a.CompleteWorkspaceCreation, value.ID).Get(ctx, nil)
	return value.ID, err
}
func StartCreate(ctx context.Context, tc client.Client, in workspace.Provision) error {
	_, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: in.WorkflowID, TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, CreateWorkspace, in.Input)
	return err
}
