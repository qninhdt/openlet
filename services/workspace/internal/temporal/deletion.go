package temporal

import (
	"context"
	"github.com/google/uuid"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"openlet/services/workspace/internal/letfs"
	"openlet/services/workspace/internal/workspace"
	"time"
)

type DeleteWorkflowInput struct {
	Start       *workspace.DeleteInput
	OperationID uuid.UUID
}
type Advance struct{ OperationID, FilesystemID uuid.UUID }

func (a *Activities) BeginDeletion(ctx context.Context, in workspace.DeleteInput) (workspace.Deletion, error) {
	v, e := a.Store.BeginDeletion(ctx, in)
	return v, businessError(e)
}
func (a *Activities) GetDeletion(ctx context.Context, id uuid.UUID) (workspace.Deletion, error) {
	v, e := a.Store.Deletion(ctx, id)
	return v, businessError(e)
}
func (a *Activities) FreezeBucket(ctx context.Context, id uuid.UUID) error {
	return a.Letfs.FreezeBucket(ctx, id)
}
func (a *Activities) ListBucketFilesystems(ctx context.Context, in workspace.Deletion) ([]uuid.UUID, error) {
	return a.Letfs.Filesystems(ctx, in.Storage.BucketID, in.Cursor)
}
func (a *Activities) EnsureFilesystemDeletion(ctx context.Context, in letfs.DeletionInput) (bool, error) {
	op, e := a.Letfs.DeleteFilesystem(ctx, in)
	if e != nil {
		return false, e
	}
	if op.State == "failed" {
		return false, temporal.NewNonRetryableApplicationError("filesystem deletion failed", "STORAGE_DELETION_FAILED", nil)
	}
	return op.State == "succeeded", nil
}
func (a *Activities) AdvanceDeletion(ctx context.Context, in Advance) error {
	return a.Store.AdvanceDeletion(ctx, in.OperationID, in.FilesystemID)
}
func (a *Activities) CompleteBucketDeletion(ctx context.Context, id uuid.UUID) error {
	return a.Letfs.CompleteBucketDeletion(ctx, id)
}
func (a *Activities) CompleteWorkspaceDeletion(ctx context.Context, id uuid.UUID) error {
	return businessError(a.Store.CompleteDeletion(ctx, id))
}
func DeleteWorkspace(ctx workflow.Context, in DeleteWorkflowInput) (uuid.UUID, error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var a *Activities
	var deletion workspace.Deletion
	if in.OperationID == uuid.Nil {
		if in.Start == nil {
			return uuid.Nil, temporal.NewNonRetryableApplicationError("deletion input required", "VALIDATION", nil)
		}
		if e := workflow.ExecuteActivity(ctx, a.BeginDeletion, *in.Start).Get(ctx, &deletion); e != nil {
			return uuid.Nil, e
		}
	} else if e := workflow.ExecuteActivity(ctx, a.GetDeletion, in.OperationID).Get(ctx, &deletion); e != nil {
		return uuid.Nil, e
	}
	op := deletion.Operation.ID
	if deletion.Operation.State == "succeeded" {
		return op, nil
	}
	// Once admitted, cancellation must not leave a destructive operation half-finished.
	ctx, cancel := workflow.NewDisconnectedContext(ctx)
	defer cancel()
	if e := workflow.ExecuteActivity(ctx, a.FreezeBucket, deletion.Storage.BucketID).Get(ctx, nil); e != nil {
		return op, e
	}
	calls := 0
	for {
		var ids []uuid.UUID
		if e := workflow.ExecuteActivity(ctx, a.ListBucketFilesystems, deletion).Get(ctx, &ids); e != nil {
			return op, e
		}
		if len(ids) == 0 {
			break
		}
		for _, id := range ids {
			for {
				var done bool
				e := workflow.ExecuteActivity(ctx, a.EnsureFilesystemDeletion, letfs.DeletionInput{FilesystemID: id, ActorID: deletion.ActorID, RequestKey: op}).Get(ctx, &done)
				if e != nil {
					return op, e
				}
				calls++
				if done {
					break
				}
				if calls >= 100 {
					return op, workflow.NewContinueAsNewError(ctx, DeleteWorkspace, DeleteWorkflowInput{OperationID: op})
				}
				if e = workflow.Sleep(ctx, time.Second); e != nil {
					return op, e
				}
			}
			if e := workflow.ExecuteActivity(ctx, a.AdvanceDeletion, Advance{op, id}).Get(ctx, nil); e != nil {
				return op, e
			}
			deletion.Cursor = id
			if calls >= 100 {
				return op, workflow.NewContinueAsNewError(ctx, DeleteWorkspace, DeleteWorkflowInput{OperationID: op})
			}
		}
	}
	if e := workflow.ExecuteActivity(ctx, a.CompleteBucketDeletion, deletion.Storage.BucketID).Get(ctx, nil); e != nil {
		return op, e
	}
	if e := workflow.ExecuteActivity(ctx, a.CompleteWorkspaceDeletion, op).Get(ctx, nil); e != nil {
		return op, e
	}
	return op, nil
}
