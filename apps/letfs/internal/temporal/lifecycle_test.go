//go:build workflow

package temporal

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
)

func TestDeleteFilesystemWaitsForScopeChildrenBeforeRemoving(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	fs, first, second := uuid.New(), uuid.New(), uuid.New()
	pages, deleted := 0, 0
	env.RegisterActivityWithOptions(func(_ context.Context, in shared.FilesystemDeletion) ([]uuid.UUID, error) {
		pages++
		require.Equal(t, fs, in.FilesystemID)
		if pages == 1 {
			require.Equal(t, uuid.Nil, in.After)
			return []uuid.UUID{first, second}, nil
		}
		require.Equal(t, second, in.After)
		require.Equal(t, 2, deleted)
		return nil, nil
	}, activity.RegisterOptions{Name: "ListScopesForDeletion"})
	env.RegisterWorkflowWithOptions(func(_ workflow.Context, in shared.ScopeDeletion) error {
		require.Equal(t, fs, in.FilesystemID)
		require.Contains(t, []uuid.UUID{first, second}, in.ScopeID)
		deleted++
		return nil
	}, workflow.RegisterOptions{Name: DeleteScopeName})
	env.RegisterActivityWithOptions(func(_ context.Context, id uuid.UUID) error {
		require.Equal(t, fs, id)
		require.Equal(t, 2, deleted)
		return nil
	}, activity.RegisterOptions{Name: "RemoveFilesystem"})
	env.ExecuteWorkflow(DeleteFilesystem, shared.FilesystemDeletion{FilesystemID: fs})
	require.NoError(t, env.GetWorkflowError())
	require.Equal(t, 2, pages)
}

func TestDeleteScopeIgnoresCallerCancellationAfterAdmission(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	in := shared.ScopeDeletion{FilesystemID: uuid.New(), ScopeID: uuid.New()}
	env.RegisterActivityWithOptions(func(ctx context.Context, got shared.ScopeDeletion) error {
		require.NoError(t, ctx.Err())
		require.Equal(t, in, got)
		return nil
	}, activity.RegisterOptions{Name: "DeleteScopeData"})
	env.SetOnActivityStartedListener(func(*activity.Info, context.Context, converter.EncodedValues) { env.CancelWorkflow() })
	env.ExecuteWorkflow(DeleteScope, in)
	require.NoError(t, env.GetWorkflowError())
}

func TestDeleteFilesystemBoundsChildrenAndContinuesAfterTheyFinish(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	in := shared.FilesystemDeletion{FilesystemID: uuid.New()}
	pages, active, peak, finished := 0, 0, 0, 0
	last := uuid.Nil
	env.RegisterActivityWithOptions(func(_ context.Context, got shared.FilesystemDeletion) ([]uuid.UUID, error) {
		require.Equal(t, last, got.After)
		require.Zero(t, active, "all children finish before the next page")
		pages++
		ids := make([]uuid.UUID, 9)
		for i := range ids {
			ids[i] = uuid.New()
		}
		last = ids[len(ids)-1]
		return ids, nil
	}, activity.RegisterOptions{Name: "ListScopesForDeletion"})
	env.RegisterWorkflowWithOptions(func(ctx workflow.Context, got shared.ScopeDeletion) error {
		require.Equal(t, in.FilesystemID, got.FilesystemID)
		active++
		peak = max(peak, active)
		if err := workflow.Sleep(ctx, time.Second); err != nil {
			return err
		}
		active--
		finished++
		return nil
	}, workflow.RegisterOptions{Name: DeleteScopeName})
	env.ExecuteWorkflow(DeleteFilesystem, in)
	var continued *workflow.ContinueAsNewError
	require.True(t, errors.As(env.GetWorkflowError(), &continued))
	require.Equal(t, 100, pages)
	require.Equal(t, 900, finished)
	require.Equal(t, 4, peak)
	require.Zero(t, active)
	var next shared.FilesystemDeletion
	require.NoError(t, converter.GetDefaultDataConverter().FromPayloads(continued.Input, &next))
	require.Equal(t, in.FilesystemID, next.FilesystemID)
	require.Equal(t, last, next.After)
}
