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
	"testing"
)

func registerRemote(env *testsuite.TestWorkflowEnvironment) {
	env.RegisterActivityWithOptions(func(context.Context, letfs.BucketInput) (letfs.Bucket, error) { return letfs.Bucket{}, nil }, activity.RegisterOptions{Name: letfs.ProvisionBucket})
	env.RegisterActivityWithOptions(func(context.Context, letfs.FilesystemInput) (letfs.Filesystem, error) { return letfs.Filesystem{}, nil }, activity.RegisterOptions{Name: letfs.ProvisionFilesystem})
	env.RegisterActivityWithOptions(func(context.Context, letfs.Provisioned) error { return nil }, activity.RegisterOptions{Name: letfs.ReleaseProvisioning})
	env.RegisterActivityWithOptions(func(context.Context, letfs.BucketScope) (uuid.UUID, error) { return uuid.Nil, nil }, activity.RegisterOptions{Name: letfs.FreezeBucket})
	env.RegisterActivityWithOptions(func(context.Context, letfs.FilesystemPage) ([]uuid.UUID, error) { return nil, nil }, activity.RegisterOptions{Name: letfs.ListFilesystems})
	env.RegisterActivityWithOptions(func(context.Context, letfs.BucketScope) error { return nil }, activity.RegisterOptions{Name: letfs.CompleteBucket})
}
func TestCreateWorkspaceUsesOwnerGeneratedMappingBeforeRelease(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	registerRemote(env)
	in := workspace.CreateInput{ActorID: uuid.New(), Key: uuid.New(), Name: "Team"}
	id, bucket, filesystem, root := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	value := workspace.Provision{Workspace: workspace.Workspace{ID: id, Status: "provisioning", LimitBytes: "100"}, Input: in}
	var a *Activities
	env.OnActivity(a.EnsureWorkspace, mock.Anything, in).Return(value, nil).Once()
	env.OnActivity(letfs.ProvisionBucket, mock.Anything, letfs.BucketInput{WorkspaceID: id, LimitBytes: "100"}).Return(letfs.Bucket{ID: bucket, LimitBytes: "100", State: "active"}, nil).Once()
	env.OnActivity(letfs.ProvisionFilesystem, mock.Anything, letfs.FilesystemInput{WorkspaceID: id, BucketID: bucket}).Return(letfs.Filesystem{ID: filesystem, BucketID: bucket, RootID: root, State: "active"}, nil).Once()
	activated := false
	env.OnActivity(a.ActivateWorkspace, mock.Anything, workspace.Storage{WorkspaceID: id, BucketID: bucket, FilesystemID: filesystem, RootID: root, LimitBytes: "100"}).Run(func(mock.Arguments) { activated = true }).Return(nil).Once()
	env.OnActivity(letfs.ReleaseProvisioning, mock.Anything, letfs.Provisioned{BucketScope: letfs.BucketScope{WorkspaceID: id, BucketID: bucket}, FilesystemID: filesystem, RootID: root}).Run(func(mock.Arguments) { require.True(t, activated) }).Return(nil).Once()
	env.OnActivity(a.CompleteWorkspaceCreation, mock.Anything, id).Return(nil).Once()
	env.ExecuteWorkflow(CreateWorkspace, in)
	require.NoError(t, env.GetWorkflowError())
	var result uuid.UUID
	require.NoError(t, env.GetWorkflowResult(&result))
	require.Equal(t, id, result)
	env.AssertExpectations(t)
}
func TestCreateWorkspaceRejectsForeignStorageResult(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	registerRemote(env)
	in := workspace.CreateInput{ActorID: uuid.New(), Key: uuid.New(), Name: "Team"}
	id := uuid.New()
	var a *Activities
	env.OnActivity(a.EnsureWorkspace, mock.Anything, in).Return(workspace.Provision{Workspace: workspace.Workspace{ID: id, Status: "provisioning", LimitBytes: "100"}}, nil).Once()
	env.OnActivity(letfs.ProvisionBucket, mock.Anything, mock.Anything).Return(letfs.Bucket{ID: uuid.New(), LimitBytes: "101", State: "active"}, nil).Once()
	env.OnActivity(a.FailWorkspace, mock.Anything, id).Return(nil).Once()
	env.ExecuteWorkflow(CreateWorkspace, in)
	require.Error(t, env.GetWorkflowError())
	env.AssertExpectations(t)
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
