//go:build workflow

package temporal

import (
	"context"
	"github.com/google/uuid"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"openlet/apps/workspace/internal/letfs"
	"openlet/apps/workspace/internal/workspace"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"testing"
)

func registerRemote(env *testsuite.TestWorkflowEnvironment) {
	env.RegisterActivityWithOptions(func(context.Context, string, *letfsv1.CreateBucketRequest) (*letfsv1.Bucket, error) { return nil, nil }, activity.RegisterOptions{Name: letfs.CreateBucket})
	env.RegisterActivityWithOptions(func(context.Context, string, *letfsv1.CreateFilesystemRequest) (*letfsv1.Filesystem, error) {
		return nil, nil
	}, activity.RegisterOptions{Name: letfs.CreateFilesystem})
	env.RegisterActivityWithOptions(func(context.Context, string, *letfsv1.ReleaseProvisioningRequest) error { return nil }, activity.RegisterOptions{Name: letfs.ReleaseProvisioning})
	env.RegisterActivityWithOptions(func(context.Context, string, *letfsv1.FreezeBucketRequest) (*letfsv1.Bucket, error) { return nil, nil }, activity.RegisterOptions{Name: letfs.FreezeBucket})
	env.RegisterActivityWithOptions(func(context.Context, string, *letfsv1.ListBucketFilesystemsRequest) (*letfsv1.ListBucketFilesystemsResponse, error) {
		return nil, nil
	}, activity.RegisterOptions{Name: letfs.ListFilesystems})
	env.RegisterActivityWithOptions(func(context.Context, string, uuid.UUID) error { return nil }, activity.RegisterOptions{Name: letfs.PrepareDeletion})
	env.RegisterActivityWithOptions(func(context.Context, string, *letfsv1.CompleteBucketDeletionRequest) (*letfsv1.Bucket, error) {
		return nil, nil
	}, activity.RegisterOptions{Name: letfs.CompleteBucket})
}
func TestCreateWorkspaceUsesOwnerGeneratedMappingBeforeRelease(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	registerRemote(env)
	in := workspace.CreateInput{ActorID: uuid.New(), Key: uuid.New(), Name: "Team"}
	id, bucket, filesystem, root := uuid.New(), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.New()
	value := workspace.Provision{Workspace: workspace.Workspace{ID: id, Status: "provisioning", LimitBytes: "100"}, Input: in}
	var a *Activities
	env.OnActivity(a.EnsureWorkspace, mock.Anything, in).Return(value, nil).Once()
	initialSync := false
	env.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Run(func(mock.Arguments) { initialSync = true }).Return(nil).Once()
	reserved := false
	env.OnActivity(a.ReserveWorkspaceStorage, mock.Anything, id).Run(func(mock.Arguments) { require.True(t, initialSync); reserved = true }).Return(workspace.Storage{WorkspaceID: id, BucketID: bucket, FilesystemID: filesystem, LimitBytes: "100"}, nil).Once()
	env.OnActivity(letfs.CreateBucket, mock.Anything, "workspace", &letfsv1.CreateBucketRequest{BucketId: bucket.String(), IdempotencyKey: bucket.String(), LimitBytes: 100}).Run(func(mock.Arguments) { require.True(t, reserved) }).Return(&letfsv1.Bucket{Id: bucket.String(), LimitBytes: 100, State: "active"}, nil).Once()
	env.OnActivity(letfs.CreateFilesystem, mock.Anything, "workspace", &letfsv1.CreateFilesystemRequest{FilesystemId: filesystem.String(), BucketId: bucket.String(), IdempotencyKey: filesystem.String(), RootName: "drive"}).Return(&letfsv1.Filesystem{Id: filesystem.String(), BucketId: bucket.String(), RootId: root.String(), State: "active"}, nil).Once()
	activated := false
	env.OnActivity(a.ActivateWorkspace, mock.Anything, workspace.Storage{WorkspaceID: id, BucketID: bucket, FilesystemID: filesystem, RootID: root, LimitBytes: "100"}).Run(func(mock.Arguments) { activated = true }).Return(nil).Once()
	env.OnActivity(letfs.ReleaseProvisioning, mock.Anything, "workspace", &letfsv1.ReleaseProvisioningRequest{BucketId: bucket.String(), FilesystemId: filesystem.String(), RootId: root.String()}).Run(func(mock.Arguments) { require.True(t, activated) }).Return(nil).Once()
	synced := false
	env.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Run(func(mock.Arguments) { require.True(t, activated); synced = true }).Return(nil).Once()
	env.OnActivity(a.CompleteWorkspaceCreation, mock.Anything, id).Run(func(mock.Arguments) { require.True(t, synced) }).Return(nil).Once()
	env.ExecuteWorkflow(CreateWorkspace, in)
	require.NoError(t, env.GetWorkflowError())
	var result uuid.UUID
	require.NoError(t, env.GetWorkflowResult(&result))
	require.Equal(t, id, result)
	env.AssertExpectations(t)
}
func TestCreateWorkspaceRejectsForeignStorageResult(t *testing.T) {
	for _, stage := range []string{"bucket", "filesystem"} {
		t.Run(stage, func(t *testing.T) {
			var suite testsuite.WorkflowTestSuite
			env := suite.NewTestWorkflowEnvironment()
			registerRemote(env)
			in := workspace.CreateInput{ActorID: uuid.New(), Key: uuid.New(), Name: "Team"}
			id, bucket, fs := uuid.New(), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
			var a *Activities
			env.OnActivity(a.EnsureWorkspace, mock.Anything, in).Return(workspace.Provision{Workspace: workspace.Workspace{ID: id, Status: "provisioning", LimitBytes: "100"}}, nil).Once()
			env.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Return(nil).Once()
			env.OnActivity(a.ReserveWorkspaceStorage, mock.Anything, id).Return(workspace.Storage{WorkspaceID: id, BucketID: bucket, FilesystemID: fs, LimitBytes: "100"}, nil).Once()
			returnedBucket := bucket.String()
			if stage == "bucket" {
				returnedBucket = uuid.NewString()
			}
			env.OnActivity(letfs.CreateBucket, mock.Anything, "workspace", mock.Anything).Return(&letfsv1.Bucket{Id: returnedBucket, LimitBytes: 100, State: "active"}, nil).Once()
			if stage == "filesystem" {
				env.OnActivity(letfs.CreateFilesystem, mock.Anything, "workspace", mock.Anything).Return(&letfsv1.Filesystem{Id: uuid.NewString(), BucketId: bucket.String(), RootId: uuid.NewString(), State: "active"}, nil).Once()
			}
			env.OnActivity(a.FailWorkspace, mock.Anything, id).Return(nil).Once()
			env.ExecuteWorkflow(CreateWorkspace, in)
			require.Error(t, env.GetWorkflowError())
			env.AssertNotCalled(t, "ActivateWorkspace", mock.Anything, mock.Anything)
			env.AssertExpectations(t)
		})
	}
}
func TestCreateWorkspaceRejectsBeforeProvisioning(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var a *Activities
	in := workspace.CreateInput{Name: "invalid"}
	env.OnActivity(a.EnsureWorkspace, mock.Anything, in).Return(workspace.Provision{}, temporal.NewNonRetryableApplicationError("rejected", "VALIDATION", nil)).Once()
	env.ExecuteWorkflow(CreateWorkspace, in)
	require.Error(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
