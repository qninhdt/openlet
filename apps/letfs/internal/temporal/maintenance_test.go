//go:build workflow

package temporal

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
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

func TestStorageMaintenanceReportsCombinedErrorsAndStillCleansObjects(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var stages []string
	env.RegisterActivityWithOptions(func(context.Context) (int, error) {
		stages = append(stages, "expire")
		return 0, temporal.NewNonRetryableApplicationError("uploads unavailable", "UPLOADS_UNAVAILABLE", nil)
	}, activity.RegisterOptions{Name: "expire_uploads_batch"})
	env.RegisterActivityWithOptions(func(context.Context) (int, error) {
		stages = append(stages, "reconcile")
		return 0, temporal.NewNonRetryableApplicationError("Temporal unavailable", "DEPENDENCY_UNAVAILABLE", nil)
	}, activity.RegisterOptions{Name: "reconcile_resources_batch"})
	env.RegisterActivityWithOptions(func(context.Context) (int, error) {
		stages = append(stages, "delete")
		return 0, nil
	}, activity.RegisterOptions{Name: "delete_objects_batch"})
	env.ExecuteWorkflow(StorageMaintenance)
	require.Equal(t, []string{"expire", "reconcile", "delete"}, stages)
	err := env.GetWorkflowError()
	require.ErrorContains(t, err, "uploads unavailable")
	require.ErrorContains(t, err, "Temporal unavailable")
}
