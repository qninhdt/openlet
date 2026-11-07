package temporal

import (
	"context"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/workflow"
	"time"
)

func (a *Activities) MarkWorkspaceDeleting(ctx context.Context, in workspace.DeleteInput) (workspace.Workspace, error) {
	value, err := a.Service.MarkWorkspaceDeleting(ctx, in)
	return value, shared.Error(err)
}
func (a *Activities) RemoveWorkspace(ctx context.Context, id uuid.UUID) error {
	return shared.Error(a.Service.RemoveWorkspace(ctx, id))
}
func DeleteWorkspace(ctx workflow.Context, in workspace.DeleteInput) (workspace.Workspace, error) {
	ctx, cancel := workflow.NewDisconnectedContext(ctx)
	defer cancel()
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second})
	var a *Activities
	var value workspace.Workspace
	if err := workflow.ExecuteActivity(ctx, a.MarkWorkspaceDeleting, in).Get(ctx, &value); err != nil {
		return value, err
	}
	child := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{TaskQueue: shared.LetFSQueue, ParentClosePolicy: enums.PARENT_CLOSE_POLICY_ABANDON})
	if err := workflow.ExecuteChildWorkflow(child, shared.DeleteFilesystemWorkflow, shared.FilesystemDeletion{FilesystemID: value.FilesystemID}).Get(ctx, nil); err != nil {
		return value, err
	}
	err := workflow.ExecuteActivity(ctx, a.RemoveWorkspace, value.ID).Get(ctx, nil)
	if err == nil {
		value.Status = "deleted"
	}
	return value, err
}
