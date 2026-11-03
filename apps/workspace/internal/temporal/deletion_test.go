//go:build workflow

package temporal

import (
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
)

func TestDeleteWorkspaceWaitsForEveryFilesystem(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var activities *Activities
	workspaceID, bucketID, first, second := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	env.OnActivity(activities.FreezeBucket, mock.Anything, bucketID).Return(nil).Once()
	env.OnActivity(activities.ListFilesystems, mock.Anything, bucketID, uuid.Nil).Return([]uuid.UUID{first, second}, nil).Once()
	env.OnActivity(activities.DeleteFilesystem, mock.Anything, first).Return(false, nil).Once()
	env.OnActivity(activities.DeleteFilesystem, mock.Anything, first).Return(true, nil).Once()
	env.OnActivity(activities.DeleteFilesystem, mock.Anything, second).Return(true, nil).Once()
	env.OnActivity(activities.ListFilesystems, mock.Anything, bucketID, second).Return([]uuid.UUID{}, nil).Once()
	env.OnActivity(activities.CompleteBucket, mock.Anything, bucketID).Return(nil).Once()
	env.OnActivity(activities.CompleteWorkspaceDeletion, mock.Anything, workspaceID).Return(nil).Once()
	env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{Workspace: workspace.Workspace{ID: workspaceID, Status: "deleting", BucketID: &bucketID}})
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}

func TestDeleteWorkspaceContinuationCarriesCursor(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var activities *Activities
	workspaceID, bucketID := uuid.New(), uuid.New()
	ids := make([]uuid.UUID, 100)
	for i := range ids {
		ids[i] = uuid.Must(uuid.NewV7())
	}
	env.OnActivity(activities.FreezeBucket, mock.Anything, bucketID).Return(nil).Once()
	env.OnActivity(activities.ListFilesystems, mock.Anything, bucketID, uuid.Nil).Return(ids, nil).Once()
	for _, id := range ids {
		env.OnActivity(activities.DeleteFilesystem, mock.Anything, id).Return(true, nil).Once()
	}
	env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{Workspace: workspace.Workspace{ID: workspaceID, Status: "deleting", BucketID: &bucketID}})
	var continued *workflow.ContinueAsNewError
	require.ErrorAs(t, env.GetWorkflowError(), &continued)
	var input DeleteWorkflowInput
	require.NoError(t, converter.GetDefaultDataConverter().FromPayloads(continued.Input, &input))
	require.Equal(t, ids[99], input.Cursor)
	env.AssertExpectations(t)
}

func TestDeleteWorkspaceWithoutStorageOnlyCompletesWorkspace(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var activities *Activities
	id := uuid.New()
	env.OnActivity(activities.CompleteWorkspaceDeletion, mock.Anything, id).Return(nil).Once()
	env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{Workspace: workspace.Workspace{ID: id, Status: "deleting"}})
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}

func TestDeleteWorkspaceBoundsPollingHistoryBeforeFilesystemCompletes(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	a := &Activities{}
	workspaceID, bucket, fs := uuid.New(), uuid.New(), uuid.New()
	env.OnActivity(a.FreezeBucket, mock.Anything, bucket).Return(nil).Once()
	env.OnActivity(a.ListFilesystems, mock.Anything, bucket, uuid.Nil).Return([]uuid.UUID{fs}, nil).Once()
	env.OnActivity(a.DeleteFilesystem, mock.Anything, fs).Return(false, nil).Times(100)
	env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{Workspace: workspace.Workspace{ID: workspaceID, Status: "deleting", BucketID: &bucket}})
	require.True(t, workflow.IsContinueAsNewError(env.GetWorkflowError()))
	env.AssertExpectations(t)
}
