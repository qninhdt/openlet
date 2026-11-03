//go:build workflow

package temporal

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/testsuite"
)

func TestStorageMaintenanceOrdersAndBoundsActivities(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var stages []string
	for _, name := range []string{"expire_uploads_batch", "reconcile_resources_batch", "delete_objects_batch"} {
		env.RegisterActivityWithOptions(func(ctx context.Context) (int, error) {
			stages = append(stages, name)
			info := activity.GetInfo(ctx)
			if name == "expire_uploads_batch" {
				require.Zero(t, info.HeartbeatTimeout)
			} else {
				require.Equal(t, 30*time.Second, info.HeartbeatTimeout)
			}
			return 0, nil
		}, activity.RegisterOptions{Name: name})
	}
	env.ExecuteWorkflow(StorageMaintenance)
	require.NoError(t, env.GetWorkflowError())
	require.Equal(t, []string{"expire_uploads_batch", "reconcile_resources_batch", "delete_objects_batch"}, stages)
}
