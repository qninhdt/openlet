//go:build workflow

package temporal

import (
	"github.com/google/uuid"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
	"openlet/apps/workspace/internal/letfs"
	"openlet/apps/workspace/internal/workspace"
	"testing"
)

func deleteFilesystemStub(workflow.Context, letfs.DeletionInput) (uuid.UUID, error) {
	return uuid.Nil, nil
}
func TestDeleteWorkspaceAwaitsAllFilesystemChildren(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	registerRemote(env)
	env.RegisterWorkflowWithOptions(deleteFilesystemStub, workflow.RegisterOptions{Name: "DeleteFilesystem"})
	id, actor, bucket, first, second := uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New()
	var a *Activities
	env.OnActivity(a.GetDeletion, mock.Anything, id).Return(workspace.Deletion{Workspace: workspace.Workspace{ID: id, Status: "deleting", BucketID: &bucket}, ActorID: actor}, nil).Once()
	scope := letfs.BucketScope{WorkspaceID: id, BucketID: bucket}
	env.OnActivity(letfs.FreezeBucket, mock.Anything, scope).Return(bucket, nil).Once()
	env.OnActivity(letfs.ListFilesystems, mock.Anything, letfs.FilesystemPage{BucketScope: scope}).Return([]uuid.UUID{first, second}, nil).Once()
	for _, fs := range []uuid.UUID{first, second} {
		env.OnWorkflow("DeleteFilesystem", mock.Anything, letfs.DeletionInput{FilesystemID: fs, ActorID: actor}).Return(fs, nil).Once()
	}
	env.OnActivity(letfs.ListFilesystems, mock.Anything, letfs.FilesystemPage{BucketScope: scope, After: second}).Return([]uuid.UUID{}, nil).Once()
	env.OnActivity(letfs.CompleteBucket, mock.Anything, scope).Return(nil).Once()
	env.OnActivity(a.CompleteWorkspaceDeletion, mock.Anything, id).Return(nil).Once()
	env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{WorkspaceID: id})
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}

func TestDeleteWorkspaceContinuationCarriesOnlyItsRemainingCursor(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	id, actor, bucket := uuid.New(), uuid.New(), uuid.New()
	scope := letfs.BucketScope{WorkspaceID: id, BucketID: bucket}
	var a *Activities
	configure := func() *testsuite.TestWorkflowEnvironment {
		env := suite.NewTestWorkflowEnvironment()
		registerRemote(env)
		env.RegisterWorkflowWithOptions(deleteFilesystemStub, workflow.RegisterOptions{Name: "DeleteFilesystem"})
		env.OnActivity(a.GetDeletion, mock.Anything, id).Return(workspace.Deletion{Workspace: workspace.Workspace{ID: id, Status: "deleting", BucketID: &bucket}, ActorID: actor}, nil).Once()
		env.OnActivity(letfs.FreezeBucket, mock.Anything, scope).Return(bucket, nil).Once()
		return env
	}
	first := configure()
	ids := make([]uuid.UUID, 100)
	for index := range ids {
		ids[index] = uuid.Must(uuid.NewV7())
		first.OnWorkflow("DeleteFilesystem", mock.Anything, letfs.DeletionInput{FilesystemID: ids[index], ActorID: actor}).Return(ids[index], nil).Once()
	}
	first.OnActivity(letfs.ListFilesystems, mock.Anything, letfs.FilesystemPage{BucketScope: scope}).Return(ids[:64], nil).Once()
	first.OnActivity(letfs.ListFilesystems, mock.Anything, letfs.FilesystemPage{BucketScope: scope, After: ids[63]}).Return(ids[64:], nil).Once()
	first.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{WorkspaceID: id})
	var continued *workflow.ContinueAsNewError
	require.ErrorAs(t, first.GetWorkflowError(), &continued)
	var input DeleteWorkflowInput
	require.NoError(t, converter.GetDefaultDataConverter().FromPayloads(continued.Input, &input))
	require.Equal(t, DeleteWorkflowInput{WorkspaceID: id, Cursor: ids[99]}, input)
	first.AssertExpectations(t)
	next := configure()
	next.OnActivity(letfs.ListFilesystems, mock.Anything, letfs.FilesystemPage{BucketScope: scope, After: ids[99]}).Return([]uuid.UUID{}, nil).Once()
	next.OnActivity(letfs.CompleteBucket, mock.Anything, scope).Return(nil).Once()
	next.OnActivity(a.CompleteWorkspaceDeletion, mock.Anything, id).Return(nil).Once()
	next.ExecuteWorkflow(DeleteWorkspace, input)
	require.NoError(t, next.GetWorkflowError())
	next.AssertExpectations(t)
}
