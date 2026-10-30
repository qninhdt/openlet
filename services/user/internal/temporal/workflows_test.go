//go:build workflow

package temporal

import (
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"openlet/services/user/internal/user"
)

func TestOnboardUser(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	v := user.Onboarding{OperationID: uuid.Must(uuid.NewV7()), UserID: uuid.Must(uuid.NewV7()), WorkspaceID: uuid.Must(uuid.NewV7()), WorkspaceKey: uuid.Must(uuid.NewV7()), State: "running"}
	env.OnActivity(a.EnsureUser, mock.Anything, "user_test").Return(v, nil).Once()
	env.OnActivity(a.EnsureInitialWorkspace, mock.Anything, v).Return("running", nil).Once()
	env.OnActivity(a.GetInitialWorkspaceStatus, mock.Anything, v).Return("succeeded", nil).Once()
	env.OnActivity(a.PublishClerkUserID, mock.Anything, "user_test", v).Return(nil).Once()
	env.OnActivity(a.CompleteOnboarding, mock.Anything, "user_test").Return(nil).Once()
	env.ExecuteWorkflow(OnboardUser, "user_test")
	if e := env.GetWorkflowError(); e != nil {
		t.Fatal(e)
	}
	env.AssertExpectations(t)
}
func TestOnboardUserCompletedNeverRecreatesWorkspace(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	v := user.Onboarding{OperationID: uuid.Must(uuid.NewV7()), State: "succeeded"}
	env.OnActivity(a.EnsureUser, mock.Anything, "user_test").Return(v, nil).Once()
	env.ExecuteWorkflow(OnboardUser, "user_test")
	if e := env.GetWorkflowError(); e != nil {
		t.Fatal(e)
	}
	env.AssertExpectations(t)
}

func TestOnboardingFailureRetainsUser(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	v := user.Onboarding{OperationID: uuid.Must(uuid.NewV7()), State: "running"}
	env.OnActivity(a.EnsureUser, mock.Anything, "subject").Return(v, nil).Once()
	env.OnActivity(a.EnsureInitialWorkspace, mock.Anything, v).Return("", temporal.NewNonRetryableApplicationError("rejected", "WORKSPACE_REJECTED", nil)).Once()
	env.OnActivity(a.FailOnboarding, mock.Anything, "subject").Return(nil).Once()
	env.ExecuteWorkflow(OnboardUser, "subject")
	if env.GetWorkflowError() == nil {
		t.Fatal("expected failure")
	}
	env.AssertExpectations(t)
}
