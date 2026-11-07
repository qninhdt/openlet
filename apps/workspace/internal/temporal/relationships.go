package temporal

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"time"
)

type Mutation = workspace.Mutation

func (a *Activities) AddMember(ctx context.Context, in Mutation) (workspace.Workspace, error) {
	value, err := a.Service.ApplyMembership(ctx, in)
	return value, shared.Error(err)
}
func (a *Activities) UpdateMembership(ctx context.Context, in Mutation) (workspace.Workspace, error) {
	value, err := a.Service.ApplyMembership(ctx, in)
	return value, shared.Error(err)
}
func (a *Activities) UpdateScopeAccess(ctx context.Context, in Mutation) (workspace.Workspace, error) {
	value, err := a.Service.UpdateScopeAccess(ctx, in)
	return value, shared.Error(err)
}
func WorkspaceChanges(ctx workflow.Context, id uuid.UUID) error {
	mutex := workflow.NewMutex(ctx)
	completed := 0
	if err := workflow.SetUpdateHandler(ctx, "mutate", func(ctx workflow.Context, in Mutation) (value workspace.Workspace, err error) {
		if in.WorkspaceID != id {
			return value, temporal.NewNonRetryableApplicationError("scope mismatch", "VALIDATION", nil)
		}
		if err = mutex.Lock(ctx); err != nil {
			return value, err
		}
		defer mutex.Unlock()
		defer func() { completed++ }()
		ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second})
		var a *Activities
		switch in.Kind {
		case "delete":
			child := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{TaskQueue: Queue, ParentClosePolicy: enums.PARENT_CLOSE_POLICY_ABANDON})
			err = workflow.ExecuteChildWorkflow(child, DeleteWorkspace, workspace.DeleteInput{WorkspaceID: id, ActorID: in.ActorID}).Get(ctx, &value)
		case "add", "join":
			if !in.ExistingScope {
				remote := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{TaskQueue: shared.LetFSQueue, StartToCloseTimeout: 30 * time.Second})
				err = workflow.ExecuteActivity(remote, shared.CreateScopesActivity, shared.ScopesCreation{AllowBlobFiles: true, AllowIndexing: true, FilesystemID: in.FilesystemID, Key: in.Key, IDs: []uuid.UUID{in.PersonalScopeID}}).Get(remote, nil)
				if err != nil {
					return value, err
				}
			}
			err = workflow.ExecuteActivity(ctx, a.AddMember, in).Get(ctx, &value)
			var application *temporal.ApplicationError
			if err != nil && !in.ExistingScope && errors.As(err, &application) && application.NonRetryable() {
				cleanup, cancel := workflow.NewDisconnectedContext(ctx)
				defer cancel()
				child := workflow.WithChildOptions(cleanup, workflow.ChildWorkflowOptions{TaskQueue: shared.LetFSQueue, ParentClosePolicy: enums.PARENT_CLOSE_POLICY_ABANDON})
				if cleanupErr := workflow.ExecuteChildWorkflow(child, shared.DeleteScopeWorkflow, shared.ScopeDeletion{FilesystemID: in.FilesystemID, ScopeID: in.PersonalScopeID}).Get(cleanup, nil); cleanupErr != nil {
					err = cleanupErr
				}
			}
		case "member":
			err = workflow.ExecuteActivity(ctx, a.UpdateMembership, in).Get(ctx, &value)
		case "scope":
			err = workflow.ExecuteActivity(ctx, a.UpdateScopeAccess, in).Get(ctx, &value)
		default:
			err = temporal.NewNonRetryableApplicationError("unknown mutation", "VALIDATION", nil)
		}
		return value, err
	}); err != nil {
		return err
	}
	if err := workflow.Await(ctx, func() bool { return completed >= 100 && workflow.AllHandlersFinished(ctx) }); err != nil {
		return err
	}
	return workflow.NewContinueAsNewError(ctx, WorkspaceChanges, id)
}
func Mutate(ctx context.Context, tc client.Client, in Mutation) (workspace.Workspace, error) {
	in.Key = uuid.Must(uuid.NewV7())
	operation := tc.NewWithStartWorkflowOperation(client.StartWorkflowOptions{ID: "workspace-changes/" + in.WorkspaceID.String(), TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE}, WorkspaceChanges, in.WorkspaceID)
	handle, err := tc.UpdateWithStartWorkflow(ctx, client.UpdateWithStartWorkflowOptions{StartWorkflowOperation: operation, UpdateOptions: client.UpdateWorkflowOptions{UpdateID: in.Key.String(), UpdateName: "mutate", Args: []any{in}, WaitForStage: client.WorkflowUpdateStageAccepted}})
	if err != nil {
		return workspace.Workspace{}, err
	}
	var value workspace.Workspace
	err = handle.Get(ctx, &value)
	return value, startError(err)
}
