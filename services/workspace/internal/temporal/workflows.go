package temporal

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"openlet/services/workspace/internal/letfs"
	"openlet/services/workspace/internal/workspace"
)

const Queue = "openlet-workspace"

type Activities struct {
	Store *workspace.Store
	Letfs *letfs.Client
}

func businessError(e error) error {
	var fault workspace.Fault
	if errors.As(e, &fault) {
		return temporal.NewNonRetryableApplicationError(fault.Code, fault.Code, e)
	}
	var remote letfs.Error
	if errors.As(e, &remote) && remote.Status >= 400 && remote.Status < 500 {
		return temporal.NewNonRetryableApplicationError("storage rejected provisioning", "STORAGE_SCOPE_CONFLICT", e)
	}
	return e
}
func (a *Activities) EnsureWorkspace(ctx context.Context, in workspace.CreateInput) (workspace.Provision, error) {
	v, e := a.Store.EnsureWorkspace(ctx, in)
	return v, businessError(e)
}
func (a *Activities) EnsureStorageBucket(ctx context.Context, in workspace.Storage) error {
	_, e := a.Letfs.EnsureBucket(ctx, letfs.BucketInput{ID: in.BucketID, ProvisionKey: "workspace/" + in.WorkspaceID.String(), LimitBytes: in.LimitBytes})
	return businessError(e)
}
func (a *Activities) EnsureDriveFilesystem(ctx context.Context, in workspace.Storage) error {
	_, e := a.Letfs.EnsureFilesystem(ctx, letfs.FilesystemInput{ID: in.FilesystemID, BucketID: in.BucketID, RootID: in.RootID, ProvisionKey: "workspace-drive/" + in.WorkspaceID.String(), RootName: "drive"})
	return businessError(e)
}
func (a *Activities) ActivateWorkspace(ctx context.Context, id uuid.UUID) error {
	return businessError(a.Store.Activate(ctx, id))
}
func (a *Activities) FailWorkspace(ctx context.Context, id uuid.UUID) error {
	return a.Store.Fail(ctx, id)
}
func CreateWorkspace(ctx workflow.Context, in workspace.CreateInput) (result uuid.UUID, err error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var a *Activities
	var provision workspace.Provision
	if e := workflow.ExecuteActivity(ctx, a.EnsureWorkspace, in).Get(ctx, &provision); e != nil {
		return uuid.Nil, e
	}
	defer func() {
		if err != nil {
			disconnected, cancel := workflow.NewDisconnectedContext(ctx)
			defer cancel()
			_ = workflow.ExecuteActivity(disconnected, a.FailWorkspace, provision.Operation.ID).Get(disconnected, nil)
		}
	}()
	if e := workflow.ExecuteActivity(ctx, a.EnsureStorageBucket, provision.Storage).Get(ctx, nil); e != nil {
		return uuid.Nil, e
	}
	if e := workflow.ExecuteActivity(ctx, a.EnsureDriveFilesystem, provision.Storage).Get(ctx, nil); e != nil {
		return uuid.Nil, e
	}
	if e := workflow.ExecuteActivity(ctx, a.ActivateWorkspace, provision.Operation.ID).Get(ctx, nil); e != nil {
		return uuid.Nil, e
	}
	return provision.Operation.ID, nil
}
