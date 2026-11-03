//go:build workflow

package temporal

import (
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
	"testing"
)

func TestRelationshipReconciliationAdvancesPastFailedResources(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	var a *Activities
	first := suite.NewTestWorkflowEnvironment()
	rejected := temporal.NewNonRetryableApplicationError("rejected", "INVALID_RELATIONSHIP", nil)
	first.OnActivity(a.ReconcileWorkspaceAdmissions, mock.Anything).Return(rejected).Once()
	first.OnActivity(a.UnreleasedProvisioning, mock.Anything).Return([]workspace.Storage{}, nil).Once()
	ids := make([]uuid.UUID, 100)
	for i := range ids {
		ids[i] = uuid.Must(uuid.NewV7())
	}
	first.OnActivity(a.WorkspaceRelationshipIDs, mock.Anything, uuid.Nil).Return(ids, nil).Once()
	first.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, ids[0]).Return(rejected).Once()
	for _, id := range ids {
		first.OnActivity(a.CleanupWorkspaceRelationships, mock.Anything, id).Return(nil).Once()
	}
	for _, id := range ids[1:] {
		first.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Return(nil).Once()
	}
	first.ExecuteWorkflow(ReconcileWorkspaces, ReconcileInput{})
	var continued *workflow.ContinueAsNewError
	require.ErrorAs(t, first.GetWorkflowError(), &continued)
	var input ReconcileInput
	require.NoError(t, converter.GetDefaultDataConverter().FromPayloads(continued.Input, &input))
	require.Equal(t, ReconcileInput{After: ids[99], Failed: true}, input)
	first.AssertExpectations(t)

	next := suite.NewTestWorkflowEnvironment()
	last := uuid.Must(uuid.NewV7())
	next.OnActivity(a.WorkspaceRelationshipIDs, mock.Anything, ids[99]).Return([]uuid.UUID{last}, nil).Once()
	next.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, last).Return(nil).Once()
	next.OnActivity(a.CleanupWorkspaceRelationships, mock.Anything, last).Return(nil).Once()
	next.ExecuteWorkflow(ReconcileWorkspaces, input)
	var failure *temporal.ApplicationError
	require.ErrorAs(t, next.GetWorkflowError(), &failure)
	require.Equal(t, "RELATIONSHIP_SYNC_FAILED", failure.Type(), "a full scan reports failure even when its last page succeeds")
	next.AssertExpectations(t)
}

func TestRelationshipReconciliationEmptyScanCompletes(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var a *Activities
	after := uuid.New()
	env.OnActivity(a.WorkspaceRelationshipIDs, mock.Anything, after).Return([]uuid.UUID{}, nil).Once()
	env.ExecuteWorkflow(ReconcileWorkspaces, ReconcileInput{After: after})
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
