package temporal

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/account/internal/user"
	sharedtemporal "github.com/qninhdt/openlet/packages/go/temporal"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"time"
)

const Queue = "openlet-account"

type Activities struct{ Service *user.Service }

func (a *Activities) EnsureUser(ctx context.Context, subject string) (user.Onboarding, error) {
	value, err := a.Service.EnsureUser(ctx, subject)
	return value, sharedtemporal.Error(err)
}
func (a *Activities) PublishClerkUserID(ctx context.Context, subject string, id uuid.UUID) error {
	return sharedtemporal.Error(a.Service.Clerk.PublishUserID(ctx, subject, id.String()))
}
func (a *Activities) CompleteOnboarding(ctx context.Context, subject string, id uuid.UUID) error {
	return sharedtemporal.Error(a.Service.Store.Complete(ctx, subject, id))
}
func (a *Activities) FailOnboarding(ctx context.Context, subject string) error {
	return sharedtemporal.Error(a.Service.Store.Fail(ctx, subject))
}

type InitialWorkspace struct {
	ID        uuid.UUID
	Completed bool
}

func (a *Activities) EnsureInitialWorkspace(ctx context.Context, actor uuid.UUID) (InitialWorkspace, error) {
	id, completed, err := a.Service.Workspace.EnsureInitial(ctx, actor)
	return InitialWorkspace{ID: id, Completed: completed}, sharedtemporal.Error(err)
}

func OnboardUser(ctx workflow.Context, subject string) (result uuid.UUID, err error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var a *Activities
	var admission user.Onboarding
	ready := false
	var admissionErr error
	if err = workflow.SetUpdateHandler(ctx, "admission", func(ctx workflow.Context) (user.Onboarding, error) {
		if err := workflow.Await(ctx, func() bool { return ready }); err != nil {
			return user.Onboarding{}, err
		}
		return admission, admissionErr
	}); err != nil {
		return uuid.Nil, err
	}
	defer func() { _ = workflow.Await(ctx, func() bool { return workflow.AllHandlersFinished(ctx) }) }()
	defer func() {
		if err != nil && !workflow.IsContinueAsNewError(err) {
			cleanup, cancel := workflow.NewDisconnectedContext(ctx)
			defer cancel()
			_ = workflow.ExecuteActivity(cleanup, a.FailOnboarding, subject).Get(cleanup, nil)
		}
	}()
	admissionErr = workflow.ExecuteActivity(ctx, a.EnsureUser, subject).Get(ctx, &admission)
	ready = true
	if admissionErr != nil {
		return uuid.Nil, admissionErr
	}
	if admission.Status == "active" {
		return admission.UserID, nil
	}
	if admission.Status != "provisioning" {
		return uuid.Nil, temporal.NewNonRetryableApplicationError("onboarding failed", "ONBOARDING_FAILED", nil)
	}
	var initial InitialWorkspace
	for polls := 0; ; polls++ {
		if polls == 100 {
			return uuid.Nil, workflow.NewContinueAsNewError(ctx, OnboardUser, subject)
		}
		if err = workflow.ExecuteActivity(ctx, a.EnsureInitialWorkspace, admission.UserID).Get(ctx, &initial); err != nil {
			return uuid.Nil, err
		}
		if initial.Completed {
			break
		}
		if err = workflow.Sleep(ctx, time.Second); err != nil {
			return uuid.Nil, err
		}
	}
	workspaceID := initial.ID
	if err = workflow.ExecuteActivity(ctx, a.PublishClerkUserID, subject, admission.UserID).Get(ctx, nil); err != nil {
		return uuid.Nil, err
	}
	if err = workflow.ExecuteActivity(ctx, a.CompleteOnboarding, subject, workspaceID).Get(ctx, nil); err != nil {
		return uuid.Nil, err
	}
	return admission.UserID, nil
}

func StartOnboarding(ctx context.Context, tc client.Client, subject string) (user.Onboarding, error) {
	operation := tc.NewWithStartWorkflowOperation(client.StartWorkflowOptions{ID: "onboard/" + subject, TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, OnboardUser, subject)
	handle, err := tc.UpdateWithStartWorkflow(ctx, client.UpdateWithStartWorkflowOptions{StartWorkflowOperation: operation, UpdateOptions: client.UpdateWorkflowOptions{UpdateName: "admission", WaitForStage: client.WorkflowUpdateStageAccepted}})
	if err != nil {
		return user.Onboarding{}, err
	}
	var value user.Onboarding
	err = handle.Get(ctx, &value)
	return value, startError(err)
}

func startError(err error) error {
	if err == nil {
		return nil
	}
	var application *temporal.ApplicationError
	if errors.As(err, &application) && application.NonRetryable() {
		return user.Fault{Code: application.Type()}
	}
	if temporal.IsCanceledError(err) {
		return context.Canceled
	}
	return err
}
