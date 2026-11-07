package temporal

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/account/internal/account"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
)

const Queue = shared.AccountQueue

type Activities struct{ Service *account.Service }

func (a *Activities) EnsureAccount(ctx context.Context, subject string) (account.Onboarding, error) {
	value, err := a.Service.EnsureAccount(ctx, subject)
	return value, shared.Error(err)
}
func (a *Activities) PublishAccountIdentity(ctx context.Context, subject string, id uuid.UUID) error {
	return shared.Error(a.Service.Clerk.PublishAccountIdentity(ctx, subject, id.String()))
}
func (a *Activities) ApplyAccountChange(ctx context.Context, in account.ManagedCreation) (account.Profile, error) {
	value, err := a.Service.ApplyAccountChange(ctx, in)
	return value, shared.Error(err)
}

func OnboardUser(ctx workflow.Context, subject string) (uuid.UUID, error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var a *Activities
	var admission account.Onboarding
	ready := false
	var admissionErr error
	if err := workflow.SetUpdateHandler(ctx, "admission", func(ctx workflow.Context) (account.Onboarding, error) {
		if err := workflow.Await(ctx, func() bool { return ready }); err != nil {
			return account.Onboarding{}, err
		}
		return admission, admissionErr
	}); err != nil {
		return uuid.Nil, err
	}
	defer func() { _ = workflow.Await(ctx, func() bool { return workflow.AllHandlersFinished(ctx) }) }()
	admissionErr = workflow.ExecuteActivity(ctx, a.EnsureAccount, subject).Get(ctx, &admission)
	ready = true
	if admissionErr != nil {
		return uuid.Nil, admissionErr
	}
	if admission.Status == "active" {
		return admission.AccountID, nil
	}
	child := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{TaskQueue: shared.WorkspaceQueue, ParentClosePolicy: enums.PARENT_CLOSE_POLICY_ABANDON})
	if err := workflow.ExecuteChildWorkflow(child, shared.CreateWorkspaceWorkflow, shared.WorkspaceCreation{ActorID: admission.AccountID, Key: admission.AccountID, Name: "My Workspace"}).Get(ctx, nil); err != nil {
		return uuid.Nil, err
	}
	if err := workflow.ExecuteActivity(ctx, a.PublishAccountIdentity, subject, admission.AccountID).Get(ctx, nil); err != nil {
		return uuid.Nil, err
	}
	return admission.AccountID, nil
}

func AccountChanges(ctx workflow.Context, in account.ManagedCreation) (account.Profile, error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var a *Activities
	var value account.Profile
	err := workflow.ExecuteActivity(ctx, a.ApplyAccountChange, in).Get(ctx, &value)
	return value, err
}

func StartOnboarding(ctx context.Context, tc client.Client, subject string) (account.Onboarding, error) {
	operation := tc.NewWithStartWorkflowOperation(client.StartWorkflowOptions{ID: "onboard/" + subject, TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, OnboardUser, subject)
	handle, err := tc.UpdateWithStartWorkflow(ctx, client.UpdateWithStartWorkflowOptions{StartWorkflowOperation: operation, UpdateOptions: client.UpdateWorkflowOptions{UpdateName: "admission", WaitForStage: client.WorkflowUpdateStageAccepted}})
	if err != nil {
		return account.Onboarding{}, err
	}
	var value account.Onboarding
	err = handle.Get(ctx, &value)
	return value, startError(err)
}
func StartManaged(ctx context.Context, tc client.Client, in account.ManagedCreation) (account.Profile, error) {
	run, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "account/" + in.ID.String(), TaskQueue: Queue, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE}, AccountChanges, in)
	if err != nil {
		return account.Profile{}, err
	}
	var value account.Profile
	err = run.Get(ctx, &value)
	return value, startError(err)
}
func startError(err error) error {
	if err == nil {
		return nil
	}
	var application *temporal.ApplicationError
	if errors.As(err, &application) && application.NonRetryable() {
		return account.Fault{Code: application.Type()}
	}
	if temporal.IsCanceledError(err) {
		return context.Canceled
	}
	return err
}
