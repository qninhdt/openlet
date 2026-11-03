//go:build workflow

package temporal

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
)

func TestDeletionCancellationDoesNotStrandAdmittedCleanup(t *testing.T) {
	for _, purge := range []bool{false, true} {
		var suite testsuite.WorkflowTestSuite
		env := suite.NewTestWorkflowEnvironment()
		input := filesystem.DeletionInput{FilesystemID: uuid.New()}
		identity, execute := input.FilesystemID, DeleteFilesystem
		if purge {
			entry := uuid.New()
			input.EntryID, identity, execute = &entry, entry, PurgeTrash
		}
		var batches int
		env.RegisterActivityWithOptions(func(ctx context.Context, in filesystem.DeletionInput) (bool, error) {
			require.NoError(t, ctx.Err())
			require.Equal(t, input, in)
			batches++
			return batches == 3, nil
		}, activity.RegisterOptions{Name: "delete_nodes_batch"})
		env.SetOnActivityStartedListener(func(info *activity.Info, _ context.Context, _ converter.EncodedValues) {
			if info.ActivityType.Name == "delete_nodes_batch" && batches == 0 {
				env.CancelWorkflow()
			}
		})
		env.ExecuteWorkflow(execute, input)
		require.NoError(t, env.GetWorkflowError())
		var result uuid.UUID
		require.NoError(t, env.GetWorkflowResult(&result))
		require.Equal(t, identity, result)
		require.Equal(t, 3, batches)
	}
}

func TestDeletionContinuationPreservesLogicalIdentity(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	entry := uuid.New()
	input := filesystem.DeletionInput{FilesystemID: uuid.New(), EntryID: &entry}
	var batches int
	env.RegisterActivityWithOptions(func(context.Context, filesystem.DeletionInput) (bool, error) { batches++; return false, nil }, activity.RegisterOptions{Name: "delete_nodes_batch"})
	env.ExecuteWorkflow(PurgeTrash, input)
	var continued *workflow.ContinueAsNewError
	require.ErrorAs(t, env.GetWorkflowError(), &continued)
	require.Equal(t, PurgeTrashName, continued.WorkflowType.Name)
	require.Equal(t, 200, batches)
	var next filesystem.DeletionInput
	require.NoError(t, converter.GetDefaultDataConverter().FromPayloads(continued.Input, &next))
	require.Equal(t, input, next)
	require.Equal(t, "purge-trash/"+input.FilesystemID.String()+"/"+entry.String(), next.WorkflowID())
}

func TestDeletionRejectsInvalidAdmissionBeforeDeleting(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	env.RegisterActivityWithOptions(func(context.Context, filesystem.DeletionInput) (bool, error) {
		return false, temporal.NewNonRetryableApplicationError("not admitted", "FILESYSTEM_NOT_DELETING", nil)
	}, activity.RegisterOptions{Name: "delete_nodes_batch"})
	env.SetTestTimeout(time.Second)
	env.ExecuteWorkflow(DeleteFilesystem, filesystem.DeletionInput{FilesystemID: uuid.New()})
	var application *temporal.ApplicationError
	require.ErrorAs(t, env.GetWorkflowError(), &application)
	require.Equal(t, "FILESYSTEM_NOT_DELETING", application.Type())
}
