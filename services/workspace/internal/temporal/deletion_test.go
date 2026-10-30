//go:build workflow

package temporal

import (
	"github.com/google/uuid"
	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/testsuite"
	"openlet/services/workspace/internal/letfs"
	"openlet/services/workspace/internal/workspace"
	"testing"
)

func TestDeleteWorkspace(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	in := workspace.DeleteInput{ActorID: uuid.New(), WorkspaceID: uuid.New(), Key: uuid.New(), Revision: "1"}
	op := uuid.New()
	bucket := uuid.New()
	fs := uuid.New()
	d := workspace.Deletion{ActorID: in.ActorID, Operation: workspace.Operation{ID: op, WorkspaceID: in.WorkspaceID, State: "running"}, Storage: workspace.Storage{BucketID: bucket}}
	a := &Activities{}
	env.OnActivity(a.BeginDeletion, mock.Anything, in).Return(d, nil).Once()
	env.OnActivity(a.FreezeBucket, mock.Anything, bucket).Return(nil).Once()
	env.OnActivity(a.ListBucketFilesystems, mock.Anything, d).Return([]uuid.UUID{fs}, nil).Once()
	remote := letfs.DeletionInput{FilesystemID: fs, ActorID: in.ActorID, RequestKey: op}
	env.OnActivity(a.EnsureFilesystemDeletion, mock.Anything, remote).Return(false, nil).Once()
	env.OnActivity(a.EnsureFilesystemDeletion, mock.Anything, remote).Return(true, nil).Once()
	env.OnActivity(a.AdvanceDeletion, mock.Anything, Advance{op, fs}).Return(nil).Once()
	d2 := d
	d2.Cursor = fs
	env.OnActivity(a.ListBucketFilesystems, mock.Anything, d2).Return([]uuid.UUID{}, nil).Once()
	env.OnActivity(a.CompleteBucketDeletion, mock.Anything, bucket).Return(nil).Once()
	env.OnActivity(a.CompleteWorkspaceDeletion, mock.Anything, op).Return(nil).Once()
	env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkflowInput{Start: &in})
	if e := env.GetWorkflowError(); e != nil {
		t.Fatal(e)
	}
	env.AssertExpectations(t)
}
