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
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
)

func TestStartErrorReturnsWorkspaceFault(t *testing.T) {
	var fault workspace.Fault
	require.ErrorAs(t, startError(temporal.NewNonRetryableApplicationError("rejected", "RESOURCE_LIMIT", nil)), &fault)
	require.Equal(t, "RESOURCE_LIMIT", fault.Code)
	require.ErrorIs(t, startError(temporal.NewCanceledError()), context.Canceled)
}

func TestCreateWorkspaceAllocatesStorageAndSavesMapping(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	in := shared.WorkspaceCreation{ActorID: uuid.New(), Key: uuid.New(), Name: "Team"}
	var fs uuid.UUID
	var scopes []uuid.UUID
	var order []string
	env.RegisterActivityWithOptions(func(_ context.Context, got shared.FilesystemCreation) error {
		fs = got.ID
		require.NotEqual(t, uuid.Nil, fs)
		require.EqualValues(t, 100, got.LimitBytes)
		order = append(order, "filesystem")
		return nil
	}, activity.RegisterOptions{Name: shared.CreateFilesystemActivity})
	env.RegisterActivityWithOptions(func(_ context.Context, got shared.ScopesCreation) error {
		require.Equal(t, fs, got.FilesystemID)
		require.Len(t, got.IDs, 2)
		scopes = got.IDs
		order = append(order, "scopes")
		return nil
	}, activity.RegisterOptions{Name: shared.CreateScopesActivity})
	env.RegisterActivityWithOptions(func(_ context.Context, got workspace.Creation) (workspace.Workspace, error) {
		require.Equal(t, in, got.Input)
		require.Equal(t, fs, got.FilesystemID)
		require.Equal(t, scopes, []uuid.UUID{got.SharedScopeID, got.PersonalScopeID})
		require.NotEqual(t, scopes[0], scopes[1])
		order = append(order, "save")
		return workspace.Workspace{ID: got.ID, FilesystemID: fs, Status: "active"}, nil
	}, activity.RegisterOptions{Name: "SaveWorkspace"})
	w := Workflows{QuotaLimit: 100}
	env.ExecuteWorkflow(w.CreateWorkspace, in)
	require.NoError(t, env.GetWorkflowError())
	require.Equal(t, []string{"filesystem", "scopes", "save"}, order)
}
