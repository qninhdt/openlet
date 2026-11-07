package temporal

import (
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"time"
)

const CopyTreeName = "CopyTree"

func CopyTree(ctx workflow.Context, in filesystem.CopyAdmission) error {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: time.Hour, HeartbeatTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 1}})
	return workflow.ExecuteActivity(ctx, "CopyTreeData", in).Get(ctx, nil)
}
