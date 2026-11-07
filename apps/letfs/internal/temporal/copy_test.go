//go:build workflow

package temporal

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/testsuite"
)

func TestCopyTreeExecutesOneActivityWithoutAutomaticRetry(t *testing.T) {
	for _, fail := range []bool{false, true} {
		var suite testsuite.WorkflowTestSuite
		env := suite.NewTestWorkflowEnvironment()
		in := filesystem.CopyAdmission{ID: uuid.New(), ScopeID: uuid.New()}
		calls := 0
		env.RegisterActivityWithOptions(func(ctx context.Context, got filesystem.CopyAdmission) error {
			calls++
			require.Equal(t, in, got)
			require.EqualValues(t, 1, activity.GetInfo(ctx).Attempt)
			require.Equal(t, 30*time.Second, activity.GetInfo(ctx).HeartbeatTimeout)
			if fail {
				return errors.New("write acknowledgement lost")
			}
			return nil
		}, activity.RegisterOptions{Name: "CopyTreeData"})
		env.ExecuteWorkflow(CopyTree, in)
		require.Equal(t, 1, calls)
		if fail {
			require.Error(t, env.GetWorkflowError())
		} else {
			require.NoError(t, env.GetWorkflowError())
		}
	}
}
