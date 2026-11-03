package temporal

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	sharedtemporal "github.com/qninhdt/openlet/packages/go/temporal"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"time"
)

const Queue = "openlet-workspace"

type Activities struct{ Service *workspace.Service }

func (a *Activities) PrepareWorkspace(ctx context.Context, in workspace.CreateInput) (workspace.Provisioning, error) {
	value, err := a.Service.Prepare(ctx, in)
	return value, sharedtemporal.Error(err)
}
func (a *Activities) CreateStorage(ctx context.Context, in workspace.Storage) (workspace.Storage, error) {
	request, err := workspace.ToClientStorage(in)
	if err != nil {
		return workspace.Storage{}, sharedtemporal.Error(err)
	}
	value, err := a.Service.Storage.CreateStorage(ctx, request)
	result := workspace.FromClientStorage(value)
	result.WorkspaceID = in.WorkspaceID
	return result, sharedtemporal.Error(err)
}
func (a *Activities) CompleteWorkspace(ctx context.Context, storage workspace.Storage, in workspace.CreateInput) error {
	return sharedtemporal.Error(a.Service.Complete(ctx, storage, in))
}
func (a *Activities) FailWorkspace(ctx context.Context, in workspace.CreateInput) error {
	return sharedtemporal.Error(a.Service.Fail(ctx, in))
}

func CreateWorkspace(ctx workflow.Context, in workspace.CreateInput) (result uuid.UUID, err error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var prepared workspace.Provisioning
	var admissionErr error
	ready := false
	if err = workflow.SetUpdateHandler(ctx, "admission", func(ctx workflow.Context, requested workspace.CreateInput) (workspace.Workspace, error) {
		if requested != in {
			return workspace.Workspace{}, temporal.NewNonRetryableApplicationError("idempotency conflict", "IDEMPOTENCY_CONFLICT", nil)
		}
		if err := workflow.Await(ctx, func() bool { return ready }); err != nil {
			return workspace.Workspace{}, err
		}
		return prepared.Workspace, admissionErr
	}); err != nil {
		return uuid.Nil, err
	}
	defer func() { _ = workflow.Await(ctx, func() bool { return workflow.AllHandlersFinished(ctx) }) }()
	var a *Activities
	defer func() {
		if err != nil {
			cleanup, cancel := workflow.NewDisconnectedContext(ctx)
			defer cancel()
			_ = workflow.ExecuteActivity(cleanup, a.FailWorkspace, in).Get(cleanup, nil)
		}
	}()
	admissionErr = workflow.ExecuteActivity(ctx, a.PrepareWorkspace, in).Get(ctx, &prepared)
	ready = true
	if admissionErr != nil {
		return uuid.Nil, admissionErr
	}
	result = prepared.Workspace.ID
	mapping := prepared.Storage
	if err = workflow.ExecuteActivity(ctx, a.CreateStorage, mapping).Get(ctx, &mapping); err != nil {
		return result, err
	}
	err = workflow.ExecuteActivity(ctx, a.CompleteWorkspace, mapping, in).Get(ctx, nil)
	return result, err
}

func StartCreate(ctx context.Context, tc client.Client, in workspace.CreateInput) (workspace.Workspace, error) {
	operation := tc.NewWithStartWorkflowOperation(client.StartWorkflowOptions{ID: "create-workspace/" + in.ActorID.String() + "/" + in.Key.String(), TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, CreateWorkspace, in)
	handle, err := tc.UpdateWithStartWorkflow(ctx, client.UpdateWithStartWorkflowOptions{StartWorkflowOperation: operation, UpdateOptions: client.UpdateWorkflowOptions{UpdateName: "admission", Args: []any{in}, WaitForStage: client.WorkflowUpdateStageAccepted}})
	if err != nil {
		return workspace.Workspace{}, err
	}
	var value workspace.Workspace
	err = handle.Get(ctx, &value)
	return value, startError(err)
}

func StartInitial(ctx context.Context, tc client.Client, in workspace.CreateInput) (workspace.Workspace, error) {
	operation := tc.NewWithStartWorkflowOperation(client.StartWorkflowOptions{ID: "create-workspace/" + in.ActorID.String() + "/" + in.Key.String(), TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, CreateWorkspace, in)
	handle, err := tc.UpdateWithStartWorkflow(ctx, client.UpdateWithStartWorkflowOptions{StartWorkflowOperation: operation, UpdateOptions: client.UpdateWorkflowOptions{UpdateName: "admission", Args: []any{in}, WaitForStage: client.WorkflowUpdateStageAccepted}})
	if err != nil {
		return workspace.Workspace{}, err
	}
	var value workspace.Workspace
	err = handle.Get(ctx, &value)
	return value, startError(err)
}

func startError(err error) error {
	if err == nil {
		return nil
	}
	var application *temporal.ApplicationError
	if errors.As(err, &application) && application.NonRetryable() {
		return workspace.Fault{Code: application.Type()}
	}
	if temporal.IsCanceledError(err) {
		return context.Canceled
	}
	return err
}
