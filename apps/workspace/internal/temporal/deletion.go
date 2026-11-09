package temporal

import (
	"context"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letaclient "github.com/qninhdt/openlet/packages/go/clients/leta"
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
func (a *Activities) ListWorkspaceLeta(ctx context.Context, workspaceID uuid.UUID, after *uuid.UUID) (letaclient.WorkspacePage, error) {
	if a.Letas == nil {
		return letaclient.WorkspacePage{}, apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "Leta teardown unavailable")
	}
	page, err := a.Letas.ListWorkspaceLeta(ctx, workspaceID, after)
	return page, shared.Error(err)
}
func (a *Activities) StopLetaForWorkspaceDeletion(ctx context.Context, workspaceID, letaID uuid.UUID) error {
	if a.Letas == nil {
		return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "Leta teardown unavailable")
	}
	return shared.Error(a.Letas.StopLetaForWorkspaceDeletion(ctx, workspaceID, letaID))
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
	stop := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 2 * time.Minute})
	var after *uuid.UUID
	for {
		var page letaclient.WorkspacePage
		if err := workflow.ExecuteActivity(ctx, a.ListWorkspaceLeta, value.ID, after).Get(ctx, &page); err != nil {
			return value, err
		}
		for offset := 0; offset < len(page.IDs); offset += 8 {
			var pending []workflow.Future
			for _, id := range page.IDs[offset:min(offset+8, len(page.IDs))] {
				pending = append(pending, workflow.ExecuteActivity(stop, a.StopLetaForWorkspaceDeletion, value.ID, id))
			}
			for _, future := range pending {
				if err := future.Get(ctx, nil); err != nil {
					return value, err
				}
			}
		}
		if page.NextCursor == nil {
			break
		}
		after = page.NextCursor
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
