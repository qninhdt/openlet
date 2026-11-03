//go:build workflow

package temporal

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
	"openlet/apps/account/internal/user"
)

func registerWorkspace(env *testsuite.TestWorkflowEnvironment) {
	env.RegisterActivityWithOptions(func(context.Context, InitialWorkspace) (uuid.UUID, error) { return uuid.Nil, nil }, activity.RegisterOptions{Name: "EnsureWorkspace"})
	env.RegisterWorkflowWithOptions(func(workflow.Context, uuid.UUID) (uuid.UUID, error) { return uuid.Nil, nil }, workflow.RegisterOptions{Name: "CreateWorkspace"})
}
func TestOnboardUserWaitsForChildAndPersistsWorkspaceBeforePublishing(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	registerWorkspace(env)
	a := &Activities{}
	admission := user.Onboarding{UserID: uuid.Must(uuid.NewV7()), Status: "provisioning"}
	workspaceID := uuid.Must(uuid.NewV7())
	env.OnActivity(a.EnsureUser, mock.Anything, "subject").Return(admission, nil).Once()
	env.OnActivity("EnsureWorkspace", mock.Anything, InitialWorkspace{ActorID: admission.UserID, Key: admission.UserID, Name: "My workspace"}).Return(workspaceID, nil).Once()
	env.OnActivity(a.SaveInitialWorkspace, mock.Anything, "subject", workspaceID).Return(nil).Once()
	env.OnWorkflow("CreateWorkspace", mock.Anything, workspaceID).Return(workspaceID, nil).Once()
	synced := false
	env.OnActivity(a.SyncAccountRelationships, mock.Anything, admission.UserID).Run(func(mock.Arguments) { synced = true }).Return(nil).Once()
	env.OnActivity(a.PublishClerkUserID, mock.Anything, "subject", admission.UserID).Run(func(mock.Arguments) { require.True(t, synced) }).Return(nil).Once()
	env.OnActivity(a.CompleteOnboarding, mock.Anything, "subject").Return(nil).Once()
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
	env.OnActivity(a.SyncAccountRelationships, mock.Anything, admission.UserID).Return(nil).Once()
	env.OnActivity(a.EnsureUser, mock.Anything, "subject").Return(admission, nil).Once()
	env.ExecuteWorkflow(OnboardUser, "subject")
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
func TestOnboardingFailureRetainsUser(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	registerWorkspace(env)
	a := &Activities{}
	admission := user.Onboarding{UserID: uuid.Must(uuid.NewV7()), Status: "provisioning"}
	workspaceID := uuid.New()
	env.OnActivity(a.EnsureUser, mock.Anything, "subject").Return(admission, nil).Once()
	env.OnActivity("EnsureWorkspace", mock.Anything, mock.Anything).Return(workspaceID, nil).Once()
	env.OnActivity(a.SaveInitialWorkspace, mock.Anything, "subject", workspaceID).Return(nil).Once()
	env.OnWorkflow("CreateWorkspace", mock.Anything, workspaceID).Return(uuid.Nil, temporal.NewNonRetryableApplicationError("rejected", "WORKSPACE_REJECTED", nil)).Once()
	env.OnActivity(a.FailOnboarding, mock.Anything, "subject").Return(nil).Once()
	env.ExecuteWorkflow(OnboardUser, "subject")
	require.Error(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}

func TestOnboardingRelationshipFailureCannotPublishCompletedIdentity(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	registerWorkspace(env)
	a := &Activities{}
	workspaceID := uuid.New()
	admission := user.Onboarding{UserID: uuid.New(), WorkspaceID: &workspaceID, Status: "provisioning"}
	env.OnActivity(a.EnsureUser, mock.Anything, "subject").Return(admission, nil).Once()
	env.OnWorkflow("CreateWorkspace", mock.Anything, workspaceID).Return(workspaceID, nil).Once()
	env.OnActivity(a.SyncAccountRelationships, mock.Anything, admission.UserID).Return(temporal.NewNonRetryableApplicationError("rejected", "INVALID_RELATIONSHIP", nil)).Once()
	env.OnActivity(a.FailOnboarding, mock.Anything, "subject").Return(nil).Once()
	env.ExecuteWorkflow(OnboardUser, "subject")
	require.Error(t, env.GetWorkflowError())
	env.AssertNotCalled(t, "PublishClerkUserID", mock.Anything, mock.Anything, mock.Anything)
	env.AssertNotCalled(t, "CompleteOnboarding", mock.Anything, mock.Anything)
	env.AssertExpectations(t)
}
