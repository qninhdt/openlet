//go:build workflow

package temporal

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/account/internal/account"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
)

func TestStartErrorReturnsNativeAccountFaults(t *testing.T) {
	err := startError(temporal.NewNonRetryableApplicationError("rejected", "ONBOARDING_FAILED", nil))
	var fault account.Fault
	require.ErrorAs(t, err, &fault)
	require.Equal(t, "ONBOARDING_FAILED", fault.Code)
	require.ErrorIs(t, startError(temporal.NewCanceledError()), context.Canceled)
}

func TestOnboardUserCreatesChildBeforePublishing(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	admission := account.Onboarding{AccountID: uuid.Must(uuid.NewV7()), Status: "pending"}
	env.RegisterWorkflowWithOptions(func(ctx workflow.Context, in shared.WorkspaceCreation) error {
		return nil
	}, workflow.RegisterOptions{Name: shared.CreateWorkspaceWorkflow})
	env.OnActivity(a.EnsureAccount, mock.Anything, "subject").Return(admission, nil).Once()
	env.OnWorkflow(shared.CreateWorkspaceWorkflow, mock.Anything, shared.WorkspaceCreation{ActorID: admission.AccountID, Key: admission.AccountID, Name: "My Workspace"}).Return(nil).Once()
	env.OnActivity(a.PublishAccountIdentity, mock.Anything, "subject", admission.AccountID).Return(nil).Once()
	env.ExecuteWorkflow(OnboardUser, "subject")
	require.NoError(t, env.GetWorkflowError())
	var id uuid.UUID
	require.NoError(t, env.GetWorkflowResult(&id))
	require.Equal(t, admission.AccountID, id)
	env.AssertExpectations(t)
}
func TestCompletedOnboardingSkipsChild(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	env.OnActivity(a.EnsureAccount, mock.Anything, "subject").Return(account.Onboarding{AccountID: uuid.New(), Status: "active"}, nil).Once()
	env.ExecuteWorkflow(OnboardUser, "subject")
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
func TestOnboardingRelationshipFailureDoesNotPublish(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	env.OnActivity(a.EnsureAccount, mock.Anything, "subject").Return(account.Onboarding{}, temporal.NewNonRetryableApplicationError("rejected", "INVALID_RELATIONSHIP", nil)).Once()
	env.ExecuteWorkflow(OnboardUser, "subject")
	require.Error(t, env.GetWorkflowError())
	env.AssertNotCalled(t, "PublishAccountIdentity", mock.Anything, mock.Anything, mock.Anything)
	env.AssertExpectations(t)
}
func TestAccountChangesPublishesManagedCreation(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	input := account.ManagedCreation{ID: uuid.New(), OwnerID: uuid.New()}
	env.OnActivity(a.ApplyAccountChange, mock.Anything, input).Return(account.Profile{ID: input.ID, Type: "agent", OwnerID: &input.OwnerID}, nil).Once()
	env.ExecuteWorkflow(AccountChanges, input)
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
