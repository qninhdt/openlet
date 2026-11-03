//go:build workflow

package temporal

import (
	"errors"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/testsuite"
)

func TestRelationshipWorkflowRetriesTheCurrentStateActivity(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var a *Activities
	id := uuid.New()
	env.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Return(errors.New("graph response lost")).Once()
	env.OnActivity(a.SyncWorkspaceRelationships, mock.Anything, id).Return(nil).Once()
	env.ExecuteWorkflow(SyncWorkspace, id)
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
