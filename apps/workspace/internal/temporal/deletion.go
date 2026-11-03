package temporal

import (
	"context"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	sharedtemporal "github.com/qninhdt/openlet/packages/go/temporal"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"time"
)

type DeleteWorkflowInput struct {
	Workspace workspace.Workspace `json:"workspace"`
	Cursor    uuid.UUID           `json:"cursor"`
}

func (a *Activities) PrepareWorkspaceDeletion(ctx context.Context, in workspace.DeleteInput) (workspace.Workspace, error) {
	value, err := a.Service.BeginDeletion(ctx, in)
	return value, sharedtemporal.Error(err)
}
func (a *Activities) CompleteWorkspaceDeletion(ctx context.Context, id uuid.UUID) error {
	return sharedtemporal.Error(a.Service.CompleteDeletion(ctx, id))
}
func (a *Activities) FreezeBucket(ctx context.Context, id uuid.UUID) error {
	return sharedtemporal.Error(a.Service.Storage.FreezeBucket(ctx, id))
}
func (a *Activities) ListFilesystems(ctx context.Context, bucket, after uuid.UUID) ([]uuid.UUID, error) {
	value, err := a.Service.Storage.ListFilesystems(ctx, bucket, after)
	return value, sharedtemporal.Error(err)
}
func (a *Activities) DeleteFilesystem(ctx context.Context, id uuid.UUID) (bool, error) {
	value, err := a.Service.Storage.DeleteFilesystem(ctx, id)
	return value, sharedtemporal.Error(err)
}
func (a *Activities) CompleteBucket(ctx context.Context, id uuid.UUID) error {
	return sharedtemporal.Error(a.Service.Storage.CompleteBucket(ctx, id))
}

func DeleteWorkspace(ctx workflow.Context, in DeleteWorkflowInput) (uuid.UUID, error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	// Once admitted, cancellation must not strand destructive cleanup.
	ctx, cancel := workflow.NewDisconnectedContext(ctx)
	defer cancel()
	var a *Activities
	value := in.Workspace
	if value.Status == "deleted" {
		return value.ID, nil
	}
	if value.BucketID != nil {
		bucket := *value.BucketID
		if err := workflow.ExecuteActivity(ctx, a.FreezeBucket, bucket).Get(ctx, nil); err != nil {
			return value.ID, err
		}
		count := 0
		for {
			var ids []uuid.UUID
			if err := workflow.ExecuteActivity(ctx, a.ListFilesystems, bucket, in.Cursor).Get(ctx, &ids); err != nil {
				return value.ID, err
			}
			if len(ids) == 0 {
				break
			}
			for _, id := range ids {
				for {
					var done bool
					if err := workflow.ExecuteActivity(ctx, a.DeleteFilesystem, id).Get(ctx, &done); err != nil {
						return value.ID, err
					}
					if done {
						break
					}
					count++
					if count >= 100 {
						return value.ID, workflow.NewContinueAsNewError(ctx, DeleteWorkspace, in)
					}
					if err := workflow.Sleep(ctx, time.Second); err != nil {
						return value.ID, err
					}
				}
				in.Cursor = id
				count++
				if count >= 100 {
					return value.ID, workflow.NewContinueAsNewError(ctx, DeleteWorkspace, in)
				}
			}
		}
		if err := workflow.ExecuteActivity(ctx, a.CompleteBucket, bucket).Get(ctx, nil); err != nil {
			return value.ID, err
		}
	}
	if err := workflow.ExecuteActivity(ctx, a.CompleteWorkspaceDeletion, value.ID).Get(ctx, nil); err != nil {
		return value.ID, err
	}
	return value.ID, nil
}
