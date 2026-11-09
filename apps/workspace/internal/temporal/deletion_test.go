//go:build workflow

package temporal

import (
	"context"
	"sync/atomic"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	letaclient "github.com/qninhdt/openlet/packages/go/clients/leta"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
)

func TestDeleteWorkspaceUsesOneFilesystemChild(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	in := workspace.DeleteInput{WorkspaceID: uuid.New(), ActorID: uuid.New()}
	fs, root := uuid.New(), uuid.New()
	var order []string
	env.RegisterActivityWithOptions(func(_ context.Context, got workspace.DeleteInput) (workspace.Workspace, error) {
		require.Equal(t, in, got)
		order = append(order, "mark")
		return workspace.Workspace{ID: in.WorkspaceID, FilesystemID: fs, Status: "deleting"}, nil
	}, activity.RegisterOptions{Name: "MarkWorkspaceDeleting"})
	env.RegisterActivityWithOptions(func(_ context.Context, workspaceID uuid.UUID, after *uuid.UUID) (letaclient.WorkspacePage, error) {
		require.Equal(t, in.WorkspaceID, workspaceID)
		require.Nil(t, after)
		order = append(order, "list roots")
		return letaclient.WorkspacePage{IDs: []uuid.UUID{root}}, nil
	}, activity.RegisterOptions{Name: "ListWorkspaceLeta"})
	env.RegisterActivityWithOptions(func(_ context.Context, workspaceID, letaID uuid.UUID) error {
		require.Equal(t, in.WorkspaceID, workspaceID)
		require.Equal(t, root, letaID)
		order = append(order, "stop root")
		return nil
	}, activity.RegisterOptions{Name: "StopLetaForWorkspaceDeletion"})
	env.RegisterWorkflowWithOptions(func(_ workflow.Context, got shared.FilesystemDeletion) error {
		require.Equal(t, fs, got.FilesystemID)
		order = append(order, "delete filesystem")
		return nil
	}, workflow.RegisterOptions{Name: shared.DeleteFilesystemWorkflow})
	env.RegisterActivityWithOptions(func(_ context.Context, id uuid.UUID) error {
		require.Equal(t, in.WorkspaceID, id)
		order = append(order, "remove")
		return nil
	}, activity.RegisterOptions{Name: "RemoveWorkspace"})
	env.ExecuteWorkflow(DeleteWorkspace, in)
	require.NoError(t, env.GetWorkflowError())
	require.Equal(t, []string{"mark", "list roots", "stop root", "delete filesystem", "remove"}, order)
}

func TestDeleteWorkspaceFailureKeepsStorageBehindStopBarrier(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	ws, root, fs := uuid.New(), uuid.New(), uuid.New()
	env.RegisterActivityWithOptions(func(context.Context, workspace.DeleteInput) (workspace.Workspace, error) {
		return workspace.Workspace{ID: ws, FilesystemID: fs, Status: "deleting"}, nil
	}, activity.RegisterOptions{Name: "MarkWorkspaceDeleting"})
	env.RegisterActivityWithOptions(func(context.Context, uuid.UUID, *uuid.UUID) (letaclient.WorkspacePage, error) {
		return letaclient.WorkspacePage{IDs: []uuid.UUID{root}}, nil
	}, activity.RegisterOptions{Name: "ListWorkspaceLeta"})
	env.RegisterActivityWithOptions(func(context.Context, uuid.UUID, uuid.UUID) error {
		return temporal.NewNonRetryableApplicationError("stop refused", "STATE_CONFLICT", nil)
	}, activity.RegisterOptions{Name: "StopLetaForWorkspaceDeletion"})
	env.RegisterWorkflowWithOptions(func(workflow.Context, shared.FilesystemDeletion) error {
		t.Fatal("storage ran before stop acknowledgement")
		return nil
	}, workflow.RegisterOptions{Name: shared.DeleteFilesystemWorkflow})
	env.ExecuteWorkflow(DeleteWorkspace, workspace.DeleteInput{WorkspaceID: ws, ActorID: uuid.New()})
	require.ErrorContains(t, env.GetWorkflowError(), "stop refused")
}

func TestDeleteWorkspacePagesAllRootsBeforeOneStorageChild(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	ws, fs := uuid.New(), uuid.New()
	ids := make([]uuid.UUID, 130)
	for i := range ids {
		ids[i] = uuid.Must(uuid.NewV7())
	}
	var stopped atomic.Int32
	env.RegisterActivityWithOptions(func(context.Context, workspace.DeleteInput) (workspace.Workspace, error) {
		return workspace.Workspace{ID: ws, FilesystemID: fs, Status: "deleting"}, nil
	}, activity.RegisterOptions{Name: "MarkWorkspaceDeleting"})
	env.RegisterActivityWithOptions(func(_ context.Context, got uuid.UUID, after *uuid.UUID) (letaclient.WorkspacePage, error) {
		require.Equal(t, ws, got)
		if after == nil {
			return letaclient.WorkspacePage{IDs: ids[:100], NextCursor: &ids[99]}, nil
		}
		require.Equal(t, ids[99], *after)
		require.EqualValues(t, 100, stopped.Load())
		return letaclient.WorkspacePage{IDs: ids[100:]}, nil
	}, activity.RegisterOptions{Name: "ListWorkspaceLeta"})
	env.RegisterActivityWithOptions(func(_ context.Context, got, root uuid.UUID) error {
		require.Equal(t, ws, got)
		require.Contains(t, ids, root)
		stopped.Add(1)
		return nil
	}, activity.RegisterOptions{Name: "StopLetaForWorkspaceDeletion"})
	env.RegisterWorkflowWithOptions(func(_ workflow.Context, in shared.FilesystemDeletion) error {
		require.Equal(t, fs, in.FilesystemID)
		require.EqualValues(t, 130, stopped.Load())
		return nil
	}, workflow.RegisterOptions{Name: shared.DeleteFilesystemWorkflow})
	env.RegisterActivityWithOptions(func(context.Context, uuid.UUID) error { return nil }, activity.RegisterOptions{Name: "RemoveWorkspace"})
	env.ExecuteWorkflow(DeleteWorkspace, workspace.DeleteInput{WorkspaceID: ws, ActorID: uuid.New()})
	require.NoError(t, env.GetWorkflowError())
	require.EqualValues(t, 130, stopped.Load())
}
