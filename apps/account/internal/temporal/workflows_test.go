//go:build workflow

package temporal

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/account/internal/user"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
)

func TestStartErrorReturnsNativeAccountFaults(t *testing.T) {
	err := startError(temporal.NewNonRetryableApplicationError("rejected", "ONBOARDING_FAILED", nil))
	var fault user.Fault
	require.ErrorAs(t, err, &fault)
	require.Equal(t, "ONBOARDING_FAILED", fault.Code)
	require.ErrorIs(t, startError(temporal.NewCanceledError()), context.Canceled)
}

func TestOnboardUserWaitsForWorkspaceAndPublishesIdentityBeforeCompletion(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	admission := user.Onboarding{UserID: uuid.Must(uuid.NewV7()), Status: "provisioning"}
	workspaceID := uuid.Must(uuid.NewV7())
	env.OnActivity(a.EnsureUser, mock.Anything, "subject").Return(admission, nil).Once()
	env.OnActivity(a.EnsureInitialWorkspace, mock.Anything, admission.UserID).Return(InitialWorkspace{ID: workspaceID, Completed: false}, nil).Once()
	env.OnActivity(a.EnsureInitialWorkspace, mock.Anything, admission.UserID).Return(InitialWorkspace{ID: workspaceID, Completed: true}, nil).Once()
	env.OnActivity(a.PublishClerkUserID, mock.Anything, "subject", admission.UserID).Return(nil).Once()
	env.OnActivity(a.CompleteOnboarding, mock.Anything, "subject", workspaceID).Return(nil).Once()
	env.ExecuteWorkflow(OnboardUser, "subject")
	require.NoError(t, env.GetWorkflowError())
	var result uuid.UUID
	require.NoError(t, env.GetWorkflowResult(&result))
	require.Equal(t, admission.UserID, result)
	env.AssertExpectations(t)
}
func TestOnboardUserCompletedNeverRecreatesWorkspace(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	admission := user.Onboarding{UserID: uuid.Must(uuid.NewV7()), Status: "active"}
	env.OnActivity(a.EnsureUser, mock.Anything, "subject").Return(admission, nil).Once()
	env.ExecuteWorkflow(OnboardUser, "subject")
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
func TestOnboardingFailureRetainsUser(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	admission := user.Onboarding{UserID: uuid.Must(uuid.NewV7()), Status: "provisioning"}
	env.OnActivity(a.EnsureUser, mock.Anything, "subject").Return(admission, nil).Once()
	env.OnActivity(a.EnsureInitialWorkspace, mock.Anything, admission.UserID).Return(InitialWorkspace{}, temporal.NewNonRetryableApplicationError("rejected", "WORKSPACE_REJECTED", nil)).Once()
	env.OnActivity(a.FailOnboarding, mock.Anything, "subject").Return(nil).Once()
	env.ExecuteWorkflow(OnboardUser, "subject")
	require.Error(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}

func TestOnboardingRelationshipFailureCannotPublishCompletedIdentity(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	env.OnActivity(a.EnsureUser, mock.Anything, "subject").Return(user.Onboarding{}, temporal.NewNonRetryableApplicationError("rejected", "INVALID_RELATIONSHIP", nil)).Once()
	env.OnActivity(a.FailOnboarding, mock.Anything, "subject").Return(nil).Once()
	env.ExecuteWorkflow(OnboardUser, "subject")
	require.Error(t, env.GetWorkflowError())
	env.AssertNotCalled(t, "PublishClerkUserID", mock.Anything, mock.Anything, mock.Anything)
	env.AssertNotCalled(t, "CompleteOnboarding", mock.Anything, mock.Anything, mock.Anything)
	env.AssertExpectations(t)
}

func TestOnboardingBoundsPollingHistoryWithoutFailingAdmission(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	admission := user.Onboarding{UserID: uuid.New(), Status: "provisioning"}
	env.OnActivity(a.EnsureUser, mock.Anything, "subject").Return(admission, nil).Once()
	env.OnActivity(a.EnsureInitialWorkspace, mock.Anything, admission.UserID).Return(InitialWorkspace{ID: uuid.New()}, nil).Times(100)
	env.ExecuteWorkflow(OnboardUser, "subject")
	require.True(t, workflow.IsContinueAsNewError(env.GetWorkflowError()))
	env.AssertNotCalled(t, "FailOnboarding", mock.Anything, mock.Anything)
	env.AssertExpectations(t)
}
