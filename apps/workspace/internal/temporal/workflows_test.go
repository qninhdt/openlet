//go:build workflow

package temporal

import (
	"context"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/letfs"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"testing"
	"time"
)

func registerRemote(env *testsuite.TestWorkflowEnvironment) {
	env.RegisterActivityWithOptions(func(context.Context, string, *letfsv1.CreateStorageRequest) (*letfsv1.CreateStorageResponse, error) {
		return nil, nil
	}, activity.RegisterOptions{Name: letfs.CreateStorage})
	env.RegisterActivityWithOptions(func(context.Context, string, *letfsv1.FreezeBucketRequest) (*letfsv1.Bucket, error) { return nil, nil }, activity.RegisterOptions{Name: letfs.FreezeBucket})
	env.RegisterActivityWithOptions(func(context.Context, string, *letfsv1.ListBucketFilesystemsRequest) (*letfsv1.ListBucketFilesystemsResponse, error) {
		return nil, nil
	}, activity.RegisterOptions{Name: letfs.ListFilesystems})
	env.RegisterActivityWithOptions(func(context.Context, string, uuid.UUID) error { return nil }, activity.RegisterOptions{Name: letfs.PrepareDeletion})
	env.RegisterActivityWithOptions(func(context.Context, string, *letfsv1.CompleteBucketDeletionRequest) (*letfsv1.Bucket, error) {
		return nil, nil
	}, activity.RegisterOptions{Name: letfs.CompleteBucket})
}
func TestCreateWorkspaceProvisionsPreparedStorageBeforeCompletion(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	registerRemote(env)
	in := workspace.CreateInput{ActorID: uuid.New(), Key: uuid.New(), Name: "Team"}
	id, bucket, fs, root := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	value := workspace.Workspace{ID: id, Status: "provisioning"}
	storage := workspace.Storage{WorkspaceID: id, BucketID: bucket, FilesystemID: fs, LimitBytes: "100"}
	var a *Activities
	env.OnActivity(a.PrepareWorkspace, mock.Anything, in).Return(Provisioning{Workspace: value, Storage: storage}, nil).After(time.Second).Once()
	env.OnActivity(letfs.CreateStorage, mock.Anything, "workspace", &letfsv1.CreateStorageRequest{
		Bucket:     &letfsv1.CreateBucketRequest{BucketId: bucket.String(), IdempotencyKey: bucket.String(), LimitBytes: 100},
		Filesystem: &letfsv1.CreateFilesystemRequest{FilesystemId: fs.String(), BucketId: bucket.String(), IdempotencyKey: fs.String(), RootName: "drive"},
	}).Return(&letfsv1.CreateStorageResponse{Bucket: &letfsv1.Bucket{Id: bucket.String(), LimitBytes: 100, State: "active"}, Filesystem: &letfsv1.Filesystem{Id: fs.String(), BucketId: bucket.String(), RootId: root.String(), State: "active"}}, nil).Once()
	storage.RootID = root
	env.OnActivity(a.CompleteWorkspace, mock.Anything, storage, in).Return(nil).Once()
	admissions := 0
	env.RegisterDelayedCallback(func() {
		env.UpdateWorkflow("admission", "matching", &testsuite.TestUpdateCallback{OnComplete: func(result any, err error) { require.NoError(t, err); require.Equal(t, value, result); admissions++ }}, in)
		changed := in
		changed.Name = "Different"
		env.UpdateWorkflow("admission", "conflict", &testsuite.TestUpdateCallback{OnComplete: func(_ any, err error) { require.ErrorContains(t, err, "IDEMPOTENCY_CONFLICT"); admissions++ }}, changed)
	}, 0)
	env.ExecuteWorkflow(CreateWorkspace, in)
	require.NoError(t, env.GetWorkflowError())
	var result uuid.UUID
	require.NoError(t, env.GetWorkflowResult(&result))
	require.Equal(t, id, result)
	require.Equal(t, 2, admissions)
	env.AssertExpectations(t)
}
func TestCreateWorkspaceRejectsForeignStorage(t *testing.T) {
	for _, stage := range []string{"bucket", "filesystem", "root", "quota"} {
		t.Run(stage, func(t *testing.T) {
			var suite testsuite.WorkflowTestSuite
			env := suite.NewTestWorkflowEnvironment()
			registerRemote(env)
			in := workspace.CreateInput{ActorID: uuid.New(), Key: uuid.New(), Name: "Team"}
			id, bucket, fs := uuid.New(), uuid.New(), uuid.New()
			var a *Activities
			env.OnActivity(a.PrepareWorkspace, mock.Anything, in).Return(Provisioning{Workspace: workspace.Workspace{ID: id}, Storage: workspace.Storage{WorkspaceID: id, BucketID: bucket, FilesystemID: fs, LimitBytes: "100"}}, nil).Once()
			response := &letfsv1.CreateStorageResponse{Bucket: &letfsv1.Bucket{Id: bucket.String(), LimitBytes: 100, State: "active"}, Filesystem: &letfsv1.Filesystem{Id: fs.String(), BucketId: bucket.String(), RootId: uuid.NewString(), State: "active"}}
			switch stage {
			case "bucket":
				response.Bucket.Id = uuid.NewString()
			case "filesystem":
				response.Filesystem.Id = uuid.NewString()
			case "root":
				response.Filesystem.RootId = "invalid"
			case "quota":
				response.Bucket.LimitBytes = 200
			}
			env.OnActivity(letfs.CreateStorage, mock.Anything, "workspace", mock.Anything).Return(response, nil).Once()
			env.OnActivity(a.FailWorkspace, mock.Anything, in).Return(nil).Once()
			env.ExecuteWorkflow(CreateWorkspace, in)
			require.Error(t, env.GetWorkflowError())
			env.AssertNotCalled(t, "CompleteWorkspace", mock.Anything, mock.Anything)
			env.AssertExpectations(t)
		})
	}
}
func TestCreateWorkspaceRejectsInvalidAdmission(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var a *Activities
	in := workspace.CreateInput{}
	env.OnActivity(a.PrepareWorkspace, mock.Anything, in).Return(Provisioning{}, temporal.NewNonRetryableApplicationError("invalid", "VALIDATION", nil)).Once()
	env.OnActivity(a.FailWorkspace, mock.Anything, in).Return(nil).Once()
	env.ExecuteWorkflow(CreateWorkspace, in)
	require.Error(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
