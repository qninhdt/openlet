package temporal

import (
	"context"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	sharedtemporal "github.com/qninhdt/openlet/packages/go/temporal"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"time"
)

type Mutation = workspace.Mutation
type PreparedMutation = workspace.PreparedMutation

func (a *Activities) PrepareMutation(ctx context.Context, in Mutation) (PreparedMutation, error) {
	value, err := a.Service.PrepareMutation(ctx, in)
	return value, sharedtemporal.Error(err)
}
func (a *Activities) ApplyMutation(ctx context.Context, in PreparedMutation) (workspace.Workspace, error) {
	value, err := a.Service.ApplyMutation(ctx, in)
	return value, sharedtemporal.Error(err)
}

// WorkspacePermissions serializes business mutations and their graph effects across worker instances.
func WorkspacePermissions(ctx workflow.Context, id uuid.UUID) error {
	activityOptions := workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}}
	mutex := workflow.NewMutex(ctx)
	completed := 0
	if err := workflow.SetUpdateHandler(ctx, "mutate", func(ctx workflow.Context, in Mutation) (workspace.Workspace, error) {
		ctx = workflow.WithActivityOptions(ctx, activityOptions)
		if in.WorkspaceID != id {
			return workspace.Workspace{}, temporal.NewNonRetryableApplicationError("scope mismatch", "VALIDATION", nil)
		}
		if err := mutex.Lock(ctx); err != nil {
			return workspace.Workspace{}, err
		}
		defer mutex.Unlock()
		defer func() { completed++ }()
		var a *Activities
		if in.Kind == "delete" {
			var value workspace.Workspace
			if err := workflow.ExecuteActivity(ctx, a.PrepareWorkspaceDeletion, workspace.DeleteInput{ActorID: in.ActorID, WorkspaceID: id, Revision: in.Revision}).Get(ctx, &value); err != nil {
				return value, err
			}
			if value.Status == "deleted" {
				return value, nil
			}
			child := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{WorkflowID: "delete-workspace/" + id.String(), TaskQueue: Queue, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE, ParentClosePolicy: enums.PARENT_CLOSE_POLICY_ABANDON, WorkflowExecutionTimeout: 7 * 24 * time.Hour})
			if err := workflow.ExecuteChildWorkflow(child, DeleteWorkspace, DeleteWorkflowInput{Workspace: value}).GetChildWorkflowExecution().Get(child, nil); err != nil && !temporal.IsWorkflowExecutionAlreadyStartedError(err) {
				return value, err
			}
			return value, nil
		}
		var prepared PreparedMutation
		local := workflow.WithLocalActivityOptions(ctx, workflow.LocalActivityOptions{StartToCloseTimeout: 5 * time.Second, RetryPolicy: activityOptions.RetryPolicy})
		if err := workflow.ExecuteLocalActivity(local, a.PrepareMutation, in).Get(ctx, &prepared); err != nil {
			return workspace.Workspace{}, err
		}
		var value workspace.Workspace
		// Scheduling the regular mutation persists preparation before its SQL changes.
		err := workflow.ExecuteActivity(ctx, a.ApplyMutation, prepared).Get(ctx, &value)
		return value, err
	}); err != nil {
		return err
	}
	if err := workflow.Await(ctx, func() bool { return completed >= 100 && workflow.AllHandlersFinished(ctx) }); err != nil {
		return err
	}
	return workflow.NewContinueAsNewError(ctx, WorkspacePermissions, id)
}

func Mutate(ctx context.Context, tc client.Client, in Mutation) (workspace.Workspace, error) {
	in.Key = uuid.Must(uuid.NewV7())
	operation := tc.NewWithStartWorkflowOperation(client.StartWorkflowOptions{ID: "workspace-permissions/" + in.WorkspaceID.String(), TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE}, WorkspacePermissions, in.WorkspaceID)
	handle, err := tc.UpdateWithStartWorkflow(ctx, client.UpdateWithStartWorkflowOptions{StartWorkflowOperation: operation, UpdateOptions: client.UpdateWorkflowOptions{UpdateID: in.Key.String(), UpdateName: "mutate", Args: []any{in}, WaitForStage: client.WorkflowUpdateStageAccepted}})
	if err != nil {
		return workspace.Workspace{}, err
	}
	var value workspace.Workspace
	err = handle.Get(ctx, &value)
	return value, startError(err)
}
