//go:build workflow

package temporal

import (
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/letfs"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
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
	id, bucket, first, second := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	if first.String() > second.String() {
		first, second = second, first
	}
	var a *Activities
	freeze := &letfsv1.FreezeBucketRequest{BucketId: bucket.String(), IdempotencyKey: bucket.String()}
	env.OnActivity(letfs.FreezeBucket, mock.Anything, "workspace", freeze).Return(&letfsv1.Bucket{Id: bucket.String(), State: "frozen"}, nil).Once()
	env.OnActivity(letfs.ListFilesystems, mock.Anything, "workspace", &letfsv1.ListBucketFilesystemsRequest{BucketId: bucket.String()}).Return(&letfsv1.ListBucketFilesystemsResponse{FilesystemIds: []string{first.String(), second.String()}}, nil).Once()
	for _, fs := range []uuid.UUID{first, second} {
		env.OnActivity(letfs.PrepareDeletion, mock.Anything, "workspace", fs).Return(nil).Once()
		env.OnWorkflow("DeleteFilesystem", mock.Anything, letfs.DeletionInput{FilesystemID: fs}).Return(fs, nil).Once()
	}
	env.OnActivity(letfs.ListFilesystems, mock.Anything, "workspace", &letfsv1.ListBucketFilesystemsRequest{BucketId: bucket.String(), AfterId: stringPointer(second.String())}).Return(&letfsv1.ListBucketFilesystemsResponse{}, nil).Once()
	env.OnActivity(letfs.CompleteBucket, mock.Anything, "workspace", &letfsv1.CompleteBucketDeletionRequest{BucketId: bucket.String(), IdempotencyKey: bucket.String()}).Return(&letfsv1.Bucket{Id: bucket.String(), State: "deleted"}, nil).Once()
	env.OnActivity(a.CompleteWorkspaceDeletion, mock.Anything, id).Return(nil).Once()
	env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{Workspace: workspace.Workspace{ID: id, Status: "deleting", BucketID: &bucket}})
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}

func TestDeleteWorkspaceContinuationCarriesOnlyItsRemainingCursor(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	id, bucket := uuid.New(), uuid.New()
	freeze := &letfsv1.FreezeBucketRequest{BucketId: bucket.String(), IdempotencyKey: bucket.String()}
	var a *Activities
	configure := func() *testsuite.TestWorkflowEnvironment {
		env := suite.NewTestWorkflowEnvironment()
		registerRemote(env)
		env.RegisterWorkflowWithOptions(deleteFilesystemStub, workflow.RegisterOptions{Name: "DeleteFilesystem"})
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
	first.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{Workspace: workspace.Workspace{ID: id, Status: "deleting", BucketID: &bucket}})
	var continued *workflow.ContinueAsNewError
	require.ErrorAs(t, first.GetWorkflowError(), &continued)
	var input DeleteWorkflowInput
	require.NoError(t, converter.GetDefaultDataConverter().FromPayloads(continued.Input, &input))
	require.Equal(t, DeleteWorkflowInput{Workspace: workspace.Workspace{ID: id, Status: "deleting", BucketID: &bucket}, Cursor: ids[99]}, input)
	first.AssertExpectations(t)
	next := configure()
	next.OnActivity(letfs.ListFilesystems, mock.Anything, "workspace", &letfsv1.ListBucketFilesystemsRequest{BucketId: bucket.String(), AfterId: stringPointer(ids[99].String())}).Return(&letfsv1.ListBucketFilesystemsResponse{}, nil).Once()
	next.OnActivity(letfs.CompleteBucket, mock.Anything, "workspace", &letfsv1.CompleteBucketDeletionRequest{BucketId: bucket.String(), IdempotencyKey: bucket.String()}).Return(&letfsv1.Bucket{Id: bucket.String(), State: "deleted"}, nil).Once()
	next.OnActivity(a.CompleteWorkspaceDeletion, mock.Anything, id).Return(nil).Once()
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
	env.OnActivity(a.CompleteWorkspaceDeletion, mock.Anything, id).Return(nil).Once()
	env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{Workspace: workspace.Workspace{ID: id, Status: "deleting"}})
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
