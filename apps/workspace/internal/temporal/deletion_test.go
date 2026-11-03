//go:build workflow

package temporal

import (
	"github.com/google/uuid"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
	"openlet/apps/workspace/internal/letfs"
	"openlet/apps/workspace/internal/workspace"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"slices"
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
	if first.String() > second.String() {
		first, second = second, first
	}
	var a *Activities
	disabled := false
	env.OnActivity(a.GetDeletion, mock.Anything, id).Return(workspace.Deletion{Workspace: workspace.Workspace{ID: id, Status: "deleting", BucketID: &bucket}, ActorID: actor}, nil).Once()
	freeze := &letfsv1.FreezeBucketRequest{BucketId: bucket.String(), IdempotencyKey: bucket.String()}
	env.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Run(func(mock.Arguments) { disabled = true }).Return(nil).Once()
	env.OnActivity(letfs.FreezeBucket, mock.Anything, "workspace", freeze).Run(func(mock.Arguments) { require.True(t, disabled) }).Return(&letfsv1.Bucket{Id: bucket.String(), State: "frozen"}, nil).Once()
	env.OnActivity(letfs.ListFilesystems, mock.Anything, "workspace", &letfsv1.ListBucketFilesystemsRequest{BucketId: bucket.String()}).Return(&letfsv1.ListBucketFilesystemsResponse{FilesystemIds: []string{first.String(), second.String()}}, nil).Once()
	for _, fs := range []uuid.UUID{first, second} {
		env.OnActivity(letfs.PrepareDeletion, mock.Anything, "workspace", fs).Return(nil).Once()
		env.OnWorkflow("DeleteFilesystem", mock.Anything, letfs.DeletionInput{FilesystemID: fs}).Return(fs, nil).Once()
	}
	env.OnActivity(letfs.ListFilesystems, mock.Anything, "workspace", &letfsv1.ListBucketFilesystemsRequest{BucketId: bucket.String(), AfterId: stringPointer(second.String())}).Return(&letfsv1.ListBucketFilesystemsResponse{}, nil).Once()
	env.OnActivity(letfs.CompleteBucket, mock.Anything, "workspace", &letfsv1.CompleteBucketDeletionRequest{BucketId: bucket.String(), IdempotencyKey: bucket.String()}).Return(&letfsv1.Bucket{Id: bucket.String(), State: "deleted"}, nil).Once()
	committed := false
	env.OnActivity(a.CompleteWorkspaceDeletion, mock.Anything, id).Run(func(mock.Arguments) { committed = true }).Return(nil).Once()
	env.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Run(func(mock.Arguments) { require.True(t, committed) }).Return(nil).Once()
	env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{WorkspaceID: id})
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}

func TestDeleteWorkspaceRelationshipFailurePreventsStorageEffects(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var a *Activities
	id := uuid.New()
	env.OnActivity(a.GetDeletion, mock.Anything, id).Return(workspace.Deletion{Workspace: workspace.Workspace{ID: id, Status: "deleting"}}, nil).Once()
	env.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Return(temporal.NewNonRetryableApplicationError("rejected", "INVALID_RELATIONSHIP", nil)).Once()
	env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{WorkspaceID: id})
	require.Error(t, env.GetWorkflowError())
	env.AssertNotCalled(t, letfs.FreezeBucket, mock.Anything, mock.Anything)
	env.AssertNotCalled(t, "CompleteWorkspaceDeletion", mock.Anything, mock.Anything)
	env.AssertExpectations(t)
}

func TestDeleteWorkspaceContinuationCarriesOnlyItsRemainingCursor(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	id, actor, bucket := uuid.New(), uuid.New(), uuid.New()
	freeze := &letfsv1.FreezeBucketRequest{BucketId: bucket.String(), IdempotencyKey: bucket.String()}
	var a *Activities
	configure := func() *testsuite.TestWorkflowEnvironment {
		env := suite.NewTestWorkflowEnvironment()
		registerRemote(env)
		env.RegisterWorkflowWithOptions(deleteFilesystemStub, workflow.RegisterOptions{Name: "DeleteFilesystem"})
		env.OnActivity(a.GetDeletion, mock.Anything, id).Return(workspace.Deletion{Workspace: workspace.Workspace{ID: id, Status: "deleting", BucketID: &bucket}, ActorID: actor}, nil).Once()
		env.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Return(nil).Once()
		env.OnActivity(letfs.FreezeBucket, mock.Anything, "workspace", freeze).Return(&letfsv1.Bucket{Id: bucket.String(), State: "frozen"}, nil).Once()
		return env
	}
	first := configure()
	ids := make([]uuid.UUID, 100)
	for index := range ids {
		ids[index] = uuid.Must(uuid.NewV7())
	}
	slices.SortFunc(ids, func(a, b uuid.UUID) int { return slices.Compare(a[:], b[:]) })
	for index := range ids {
		first.OnActivity(letfs.PrepareDeletion, mock.Anything, "workspace", ids[index]).Return(nil).Once()
		first.OnWorkflow("DeleteFilesystem", mock.Anything, letfs.DeletionInput{FilesystemID: ids[index]}).Return(ids[index], nil).Once()
	}
	first.OnActivity(letfs.ListFilesystems, mock.Anything, "workspace", &letfsv1.ListBucketFilesystemsRequest{BucketId: bucket.String()}).Return(filesystemPage(ids[:64]), nil).Once()
	first.OnActivity(letfs.ListFilesystems, mock.Anything, "workspace", &letfsv1.ListBucketFilesystemsRequest{BucketId: bucket.String(), AfterId: stringPointer(ids[63].String())}).Return(filesystemPage(ids[64:]), nil).Once()
	first.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{WorkspaceID: id})
	var continued *workflow.ContinueAsNewError
	require.ErrorAs(t, first.GetWorkflowError(), &continued)
	var input DeleteWorkflowInput
	require.NoError(t, converter.GetDefaultDataConverter().FromPayloads(continued.Input, &input))
	require.Equal(t, DeleteWorkflowInput{WorkspaceID: id, Cursor: ids[99]}, input)
	first.AssertExpectations(t)
	next := configure()
	next.OnActivity(letfs.ListFilesystems, mock.Anything, "workspace", &letfsv1.ListBucketFilesystemsRequest{BucketId: bucket.String(), AfterId: stringPointer(ids[99].String())}).Return(&letfsv1.ListBucketFilesystemsResponse{}, nil).Once()
	next.OnActivity(letfs.CompleteBucket, mock.Anything, "workspace", &letfsv1.CompleteBucketDeletionRequest{BucketId: bucket.String(), IdempotencyKey: bucket.String()}).Return(&letfsv1.Bucket{Id: bucket.String(), State: "deleted"}, nil).Once()
	next.OnActivity(a.CompleteWorkspaceDeletion, mock.Anything, id).Return(nil).Once()
	next.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Return(nil).Once()
	next.ExecuteWorkflow(DeleteWorkspace, input)
	require.NoError(t, next.GetWorkflowError())
	next.AssertExpectations(t)
}

func stringPointer(value string) *string { return &value }
func filesystemPage(ids []uuid.UUID) *letfsv1.ListBucketFilesystemsResponse {
	result := &letfsv1.ListBucketFilesystemsResponse{}
	for _, id := range ids {
		result.FilesystemIds = append(result.FilesystemIds, id.String())
	}
	return result
}
func TestDeleteWorkspaceWithoutReservedStorageHasNoRemoteEffects(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var a *Activities
	id := uuid.New()
	env.OnActivity(a.GetDeletion, mock.Anything, id).Return(workspace.Deletion{Workspace: workspace.Workspace{ID: id, Status: "deleting"}}, nil).Once()
	env.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Return(nil).Twice()
	env.OnActivity(a.CompleteWorkspaceDeletion, mock.Anything, id).Return(nil).Once()
	env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{WorkspaceID: id})
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
