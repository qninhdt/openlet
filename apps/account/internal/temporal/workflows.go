package temporal

import (
	"context"
	"errors"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/account/internal/clerk"
	"github.com/qninhdt/openlet/apps/account/internal/user"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"time"
)

const Queue = "openlet-account"

type Activities struct {
	Store *user.Store
	Clerk clerk.Client
	Graph v1.PermissionsServiceClient
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
	if err != nil {
		return value, businessError(err)
	}
	err = a.Store.SyncRelationships(ctx, a.Graph, value.UserID)
	return value, err
}
func (a *Activities) PublishClerkUserID(ctx context.Context, subject string, id uuid.UUID) error {
	return a.Clerk.PublishUserID(ctx, subject, id.String())
}
func (a *Activities) CompleteOnboarding(ctx context.Context, subject string, id uuid.UUID) error {
	return businessError(a.Store.Complete(ctx, subject, id))
}
func (a *Activities) FailOnboarding(ctx context.Context, subject string) error {
	return a.Store.Fail(ctx, subject)
}

// The Workspace workflow owns this input contract; no Account-to-Workspace Go dependency.
type InitialWorkspace struct {
	ActorID uuid.UUID `json:"actor_id"`
	Key     uuid.UUID `json:"request_key"`
	Name    string    `json:"name"`
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
		if err != nil {
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
	child := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{WorkflowID: "create-workspace/" + admission.UserID.String() + "/" + admission.UserID.String(), TaskQueue: "openlet-workspace", WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour})
	var workspaceID uuid.UUID
	if err = workflow.ExecuteChildWorkflow(child, "CreateWorkspace", InitialWorkspace{ActorID: admission.UserID, Key: admission.UserID, Name: "My workspace"}).Get(child, &workspaceID); err != nil {
		return uuid.Nil, err
	}
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
	return value, err
}
