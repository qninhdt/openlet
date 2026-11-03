//go:build workflow

package temporal

import (
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/testsuite"
	"testing"
)

func TestWorkspaceMaintenancePrunesReceipts(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var a *Activities
	env.OnActivity(a.PruneReceipts, mock.Anything).Return(nil).Once()
	env.ExecuteWorkflow(WorkspaceMaintenance)
	require.NoError(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
