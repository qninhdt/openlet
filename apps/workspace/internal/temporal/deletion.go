package temporal

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"openlet/apps/workspace/internal/letfs"
	"openlet/apps/workspace/internal/workspace"
	"time"
)

type DeleteWorkflowInput struct {
	WorkspaceID uuid.UUID `json:"workspace_id"`
	Cursor      uuid.UUID `json:"cursor"`
}

func (a *Activities) GetDeletion(ctx context.Context, id uuid.UUID) (workspace.Deletion, error) {
	value, err := a.Store.Deletion(ctx, id)
	return value, businessError(err)
}
func (a *Activities) CompleteWorkspaceDeletion(ctx context.Context, id uuid.UUID) error {
	return businessError(a.Store.CompleteDeletion(ctx, id))
}
func DeleteWorkspace(ctx workflow.Context, in DeleteWorkflowInput) (uuid.UUID, error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	// Once admitted, cancellation must not strand destructive cleanup.
	ctx, cancel := workflow.NewDisconnectedContext(ctx)
	defer cancel()
	var a *Activities
	var deletion workspace.Deletion
	if err := workflow.ExecuteActivity(ctx, a.GetDeletion, in.WorkspaceID).Get(ctx, &deletion); err != nil {
		return in.WorkspaceID, err
	}
	value := deletion.Workspace
	if value.Status == "deleted" {
		return value.ID, nil
	}
	scope := letfs.BucketScope{WorkspaceID: value.ID}
	if value.BucketID != nil {
		scope.BucketID = *value.BucketID
	}
	remote := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{TaskQueue: letfs.Queue, StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	if err := workflow.ExecuteActivity(remote, letfs.FreezeBucket, scope).Get(ctx, &scope.BucketID); err != nil {
		return value.ID, err
	}
	count := 0
	for {
		var ids []uuid.UUID
		if err := workflow.ExecuteActivity(remote, letfs.ListFilesystems, letfs.FilesystemPage{BucketScope: scope, After: in.Cursor}).Get(ctx, &ids); err != nil {
			return value.ID, err
		}
		if len(ids) == 0 {
			break
		}
		for _, id := range ids {
			childCtx := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{WorkflowID: "delete-filesystem/" + id.String() + "/" + workflow.GetInfo(ctx).WorkflowExecution.RunID, TaskQueue: letfs.Queue, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, ParentClosePolicy: enums.PARENT_CLOSE_POLICY_ABANDON, WorkflowExecutionTimeout: 7 * 24 * time.Hour})
			child := workflow.ExecuteChildWorkflow(childCtx, "DeleteFilesystem", letfs.DeletionInput{FilesystemID: id, ActorID: deletion.ActorID})
			if err := child.GetChildWorkflowExecution().Get(ctx, nil); err != nil {
				return value.ID, err
			}
			if err := child.Get(ctx, nil); err != nil {
				return value.ID, err
			}
			in.Cursor = id
			count++
			if count >= 100 {
				return value.ID, workflow.NewContinueAsNewError(ctx, DeleteWorkspace, in)
			}
		}
	}
	if err := workflow.ExecuteActivity(remote, letfs.CompleteBucket, scope).Get(ctx, nil); err != nil {
		return value.ID, err
	}
	if err := workflow.ExecuteActivity(ctx, a.CompleteWorkspaceDeletion, value.ID).Get(ctx, nil); err != nil {
		return value.ID, err
	}
	return value.ID, nil
}
func StartDelete(ctx context.Context, tc client.Client, store *workspace.Store, id uuid.UUID) error {
	// A closed execution may resume only while the durable resource is still deleting.
	deletion, err := store.Deletion(ctx, id)
	if err != nil {
		return err
	}
	if deletion.Workspace.Status == "deleted" {
		return nil
	}
	workflowID := "delete-workspace/" + id.String()
	policy := enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE
	description, err := tc.DescribeWorkflowExecution(ctx, workflowID, "")
	var missing *serviceerror.NotFound
	if err != nil && !errors.As(err, &missing) {
		return err
	}
	if err == nil {
		switch description.WorkflowExecutionInfo.Status {
		case enums.WORKFLOW_EXECUTION_STATUS_COMPLETED, enums.WORKFLOW_EXECUTION_STATUS_FAILED, enums.WORKFLOW_EXECUTION_STATUS_CANCELED, enums.WORKFLOW_EXECUTION_STATUS_TERMINATED, enums.WORKFLOW_EXECUTION_STATUS_TIMED_OUT:
			if err = store.FailDeletion(ctx, id); err != nil {
				return err
			}
			policy = enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE
		default:
			return nil
		}
	}
	_, err = tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: workflowID, TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: policy, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, DeleteWorkspace, DeleteWorkflowInput{WorkspaceID: id})
	return err
}
