//go:build workflow

package temporal

import (
	"github.com/google/uuid"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
	"testing"
)

func TestRelationshipReconciliationAdvancesPastFailedPages(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	var a *Activities
	first := suite.NewTestWorkflowEnvironment()
	rejected := temporal.NewNonRetryableApplicationError("rejected", "INVALID_RELATIONSHIP", nil)
	first.OnActivity(a.ReconcileOnboarding, mock.Anything).Return(rejected).Once()
	ids := make([]uuid.UUID, 100)
	for i := range ids {
		ids[i] = uuid.Must(uuid.NewV7())
	}
	first.OnActivity(a.AccountRelationshipIDs, mock.Anything, uuid.Nil).Return(ids, nil).Once()
	first.OnActivity(a.SyncAccountRelationshipBatch, mock.Anything, ids).Return(rejected).Once()
	first.ExecuteWorkflow(ReconcileAccounts, ReconcileInput{})
	var continued *workflow.ContinueAsNewError
	require.ErrorAs(t, first.GetWorkflowError(), &continued)
	var input ReconcileInput
	require.NoError(t, converter.GetDefaultDataConverter().FromPayloads(continued.Input, &input))
	require.Equal(t, ReconcileInput{After: ids[99], Failed: true}, input)
	first.AssertExpectations(t)

	next := suite.NewTestWorkflowEnvironment()
	last := uuid.Must(uuid.NewV7())
	next.OnActivity(a.AccountRelationshipIDs, mock.Anything, ids[99]).Return([]uuid.UUID{last}, nil).Once()
	next.OnActivity(a.SyncAccountRelationshipBatch, mock.Anything, []uuid.UUID{last}).Return(nil).Once()
	next.ExecuteWorkflow(ReconcileAccounts, input)
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
	env.OnActivity(a.AccountRelationshipIDs, mock.Anything, after).Return([]uuid.UUID{}, nil).Once()
	env.ExecuteWorkflow(ReconcileAccounts, ReconcileInput{After: after})
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
