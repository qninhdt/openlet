package temporal

import (
	"context"
	"errors"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"time"
)

func (a *Activities) PruneReceipts(ctx context.Context) error { return a.Store.PruneReceipts(ctx) }
func WorkspaceMaintenance(ctx workflow.Context) error {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 3}})
	var a *Activities
	return workflow.ExecuteActivity(ctx, a.PruneReceipts).Get(ctx, nil)
}
func EnsureMaintenance(ctx context.Context, tc client.Client) error {
	_, err := tc.ScheduleClient().Create(ctx, client.ScheduleOptions{ID: "workspace-maintenance", Spec: client.ScheduleSpec{Intervals: []client.ScheduleIntervalSpec{{Every: 5 * time.Minute}}}, Action: &client.ScheduleWorkflowAction{ID: "workspace-maintenance", Workflow: WorkspaceMaintenance, TaskQueue: Queue}, Overlap: enums.SCHEDULE_OVERLAP_POLICY_SKIP})
	if errors.Is(err, temporal.ErrScheduleAlreadyRunning) {
		return nil
	}
	return err
}
