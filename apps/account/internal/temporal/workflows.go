package temporal

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"openlet/apps/account/internal/clerk"
	"openlet/apps/account/internal/user"
)

const Queue = "openlet-account"

type Activities struct {
	Store    *user.Store
	Clerk    clerk.Client
	Temporal client.Client
}

func businessError(err error) error {
	var fault user.Fault
	if errors.As(err, &fault) {
		return temporal.NewNonRetryableApplicationError(fault.Code, fault.Code, err)
	}
	return err
}
func (a *Activities) EnsureUser(ctx context.Context, subject string) (user.Onboarding, error) {
	value, err := a.Store.EnsureUser(ctx, subject)
	return value, businessError(err)
}
func (a *Activities) SaveInitialWorkspace(ctx context.Context, subject string, id uuid.UUID) error {
	return businessError(a.Store.SaveWorkspace(ctx, subject, id))
}
func (a *Activities) PublishClerkUserID(ctx context.Context, subject string, id uuid.UUID) error {
	return a.Clerk.PublishUserID(ctx, subject, id.String())
}
func (a *Activities) CompleteOnboarding(ctx context.Context, subject string) error {
	return businessError(a.Store.Complete(ctx, subject))
}
func (a *Activities) FailOnboarding(ctx context.Context, subject string) error {
	return a.Store.Fail(ctx, subject)
}

// This JSON contract is owned by the Workspace workflow, without a Go module dependency.
type InitialWorkspace struct {
	ActorID uuid.UUID `json:"actor_id"`
	Key     uuid.UUID `json:"request_key"`
	Name    string    `json:"name"`
}

func OnboardUser(ctx workflow.Context, subject string) (result uuid.UUID, err error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var a *Activities
	var admission user.Onboarding
	if err = workflow.ExecuteActivity(ctx, a.EnsureUser, subject).Get(ctx, &admission); err != nil {
		return uuid.Nil, err
	}
	if admission.Status == "active" {
		return admission.UserID, nil
	}
	if admission.Status != "provisioning" {
		return uuid.Nil, temporal.NewNonRetryableApplicationError("onboarding failed", "ONBOARDING_FAILED", nil)
	}
	defer func() {
		if err != nil {
			disconnected, cancel := workflow.NewDisconnectedContext(ctx)
			defer cancel()
			_ = workflow.ExecuteActivity(disconnected, a.FailOnboarding, subject).Get(disconnected, nil)
		}
	}()
	if admission.WorkspaceID == nil {
		child := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{WorkflowID: "initial-workspace/" + admission.UserID.String(), TaskQueue: "openlet-workspace", WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour})
		var workspaceID uuid.UUID
		if err = workflow.ExecuteChildWorkflow(child, "CreateWorkspace", InitialWorkspace{ActorID: admission.UserID, Key: admission.UserID, Name: "My workspace"}).Get(child, &workspaceID); err != nil {
			return uuid.Nil, err
		}
		if err = workflow.ExecuteActivity(ctx, a.SaveInitialWorkspace, subject, workspaceID).Get(ctx, nil); err != nil {
			return uuid.Nil, err
		}
	}
	if err = workflow.ExecuteActivity(ctx, a.PublishClerkUserID, subject, admission.UserID).Get(ctx, nil); err != nil {
		return uuid.Nil, err
	}
	if err = workflow.ExecuteActivity(ctx, a.CompleteOnboarding, subject).Get(ctx, nil); err != nil {
		return uuid.Nil, err
	}
	return admission.UserID, nil
}

func StartOnboarding(ctx context.Context, tc client.Client, subject string) error {
	_, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "onboard/" + subject, TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_FAIL, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, OnboardUser, subject)
	return err
}

func (a *Activities) ReconcileOnboarding(ctx context.Context) error {
	subjects, err := a.Store.Pending(ctx)
	if err != nil {
		return err
	}
	for _, subject := range subjects {
		description, err := a.Temporal.DescribeWorkflowExecution(ctx, "onboard/"+subject, "")
		var missing *serviceerror.NotFound
		if errors.As(err, &missing) {
			if err = StartOnboarding(ctx, a.Temporal, subject); err != nil {
				return err
			}
			continue
		}
		if err != nil {
			return err
		}
		switch description.WorkflowExecutionInfo.Status {
		case enums.WORKFLOW_EXECUTION_STATUS_COMPLETED,
			enums.WORKFLOW_EXECUTION_STATUS_FAILED,
			enums.WORKFLOW_EXECUTION_STATUS_CANCELED,
			enums.WORKFLOW_EXECUTION_STATUS_TERMINATED,
			enums.WORKFLOW_EXECUTION_STATUS_TIMED_OUT:
			if err = a.Store.Fail(ctx, subject); err != nil {
				return err
			}
		}
	}
	return nil
}

func ReconcileAccounts(ctx workflow.Context) error {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 2 * time.Minute, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 3}})
	var a *Activities
	return workflow.ExecuteActivity(ctx, a.ReconcileOnboarding).Get(ctx, nil)
}

func EnsureReconciliation(ctx context.Context, tc client.Client) error {
	_, err := tc.ScheduleClient().Create(ctx, client.ScheduleOptions{ID: "account-reconciliation", Spec: client.ScheduleSpec{Intervals: []client.ScheduleIntervalSpec{{Every: 5 * time.Minute}}}, Action: &client.ScheduleWorkflowAction{ID: "reconcile-accounts", Workflow: ReconcileAccounts, TaskQueue: Queue, WorkflowExecutionTimeout: 4 * time.Minute}, Overlap: enums.SCHEDULE_OVERLAP_POLICY_SKIP, TriggerImmediately: true})
	if errors.Is(err, temporal.ErrScheduleAlreadyRunning) {
		return tc.ScheduleClient().GetHandle(ctx, "account-reconciliation").Trigger(ctx, client.ScheduleTriggerOptions{Overlap: enums.SCHEDULE_OVERLAP_POLICY_SKIP})
	}
	return err
}
