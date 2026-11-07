//go:build workflow

package temporal

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
)

func TestDeleteWorkspaceUsesOneFilesystemChild(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	in := workspace.DeleteInput{WorkspaceID: uuid.New(), ActorID: uuid.New()}
	fs := uuid.New()
	var order []string
	env.RegisterActivityWithOptions(func(_ context.Context, got workspace.DeleteInput) (workspace.Workspace, error) {
		require.Equal(t, in, got)
		order = append(order, "mark")
		return workspace.Workspace{ID: in.WorkspaceID, FilesystemID: fs, Status: "deleting"}, nil
	}, activity.RegisterOptions{Name: "MarkWorkspaceDeleting"})
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
	require.Equal(t, []string{"mark", "delete filesystem", "remove"}, order)
}
