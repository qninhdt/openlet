//go:build workflow

package temporal

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
)

func TestStartErrorReturnsNativeWorkspaceFaults(t *testing.T) {
	err := startError(temporal.NewNonRetryableApplicationError("rejected", "RESOURCE_LIMIT", nil))
	var fault workspace.Fault
	require.ErrorAs(t, err, &fault)
	require.Equal(t, "RESOURCE_LIMIT", fault.Code)
	require.ErrorIs(t, startError(temporal.NewCanceledError()), context.Canceled)
}

func TestCreateWorkspaceProvisionsPreparedStorageBeforeCompletion(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	in := workspace.CreateInput{ActorID: uuid.New(), Key: uuid.New(), Name: "Team"}
	id, bucket, filesystem, root := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	value := workspace.Workspace{ID: id, Status: "provisioning"}
	storage := workspace.Storage{WorkspaceID: id, BucketID: bucket, FilesystemID: filesystem, LimitBytes: "100"}
	completedStorage := storage
	completedStorage.RootID = root
	var activities *Activities
	env.OnActivity(activities.PrepareWorkspace, mock.Anything, in).Return(workspace.Provisioning{Workspace: value, Storage: storage}, nil).After(time.Second).Once()
	env.OnActivity(activities.CreateStorage, mock.Anything, storage).Return(completedStorage, nil).Once()
	env.OnActivity(activities.CompleteWorkspace, mock.Anything, completedStorage, in).Return(nil).Once()
	admissions := 0
	env.RegisterDelayedCallback(func() {
		env.UpdateWorkflow("admission", "matching", &testsuite.TestUpdateCallback{OnComplete: func(result any, err error) {
			require.NoError(t, err)
			require.Equal(t, value, result)
			admissions++
		}}, in)
		changed := in
		changed.Name = "Different"
		env.UpdateWorkflow("admission", "conflict", &testsuite.TestUpdateCallback{OnComplete: func(_ any, err error) {
			require.ErrorContains(t, err, "IDEMPOTENCY_CONFLICT")
			admissions++
		}}, changed)
	}, 0)
	env.ExecuteWorkflow(CreateWorkspace, in)
	require.NoError(t, env.GetWorkflowError())
	var result uuid.UUID
	require.NoError(t, env.GetWorkflowResult(&result))
	require.Equal(t, id, result)
	require.Equal(t, 2, admissions)
	env.AssertExpectations(t)
}

func TestCreateWorkspaceStorageFailureMarksWorkspaceFailed(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	in := workspace.CreateInput{ActorID: uuid.New(), Key: uuid.New(), Name: "Team"}
	storage := workspace.Storage{WorkspaceID: uuid.New(), BucketID: uuid.New(), FilesystemID: uuid.New(), LimitBytes: "100"}
	var activities *Activities
	env.OnActivity(activities.PrepareWorkspace, mock.Anything, in).Return(workspace.Provisioning{Workspace: workspace.Workspace{ID: storage.WorkspaceID}, Storage: storage}, nil).Once()
	env.OnActivity(activities.CreateStorage, mock.Anything, storage).Return(workspace.Storage{}, temporal.NewNonRetryableApplicationError("rejected", "STORAGE_SCOPE_CONFLICT", nil)).Once()
	env.OnActivity(activities.FailWorkspace, mock.Anything, in).Return(nil).Once()
	env.ExecuteWorkflow(CreateWorkspace, in)
	require.Error(t, env.GetWorkflowError())
	env.AssertNotCalled(t, "CompleteWorkspace", mock.Anything, mock.Anything)
	env.AssertExpectations(t)
}

func TestCreateWorkspaceRejectsInvalidAdmission(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var activities *Activities
	in := workspace.CreateInput{}
	env.OnActivity(activities.PrepareWorkspace, mock.Anything, in).Return(workspace.Provisioning{}, temporal.NewNonRetryableApplicationError("invalid", "VALIDATION", nil)).Once()
	env.OnActivity(activities.FailWorkspace, mock.Anything, in).Return(nil).Once()
	env.ExecuteWorkflow(CreateWorkspace, in)
	require.Error(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
