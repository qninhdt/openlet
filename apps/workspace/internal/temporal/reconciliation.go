package temporal

import (
	"context"
	"errors"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"openlet/apps/workspace/internal/letfs"
	"openlet/apps/workspace/internal/workspace"
	"time"
)

func (a *Activities) ReconcileWorkspaceAdmissions(ctx context.Context) error {
	pending, err := a.Store.Pending(ctx)
	if err != nil {
		return err
	}
	for _, value := range pending {
		id := value.Provision.WorkflowID
		if value.Status == "deleting" {
			if err = StartDelete(ctx, a.Temporal, a.Store, value.ID); err != nil {
				return err
			}
			continue
		}
		description, err := a.Temporal.DescribeWorkflowExecution(ctx, id, "")
		var missing *serviceerror.NotFound
		if errors.As(err, &missing) {
			err = StartCreate(ctx, a.Temporal, value.Provision)
			if err != nil {
				return err
			}
			continue
		}
		if err != nil {
			return err
		}
		switch description.WorkflowExecutionInfo.Status {
		case enums.WORKFLOW_EXECUTION_STATUS_COMPLETED, enums.WORKFLOW_EXECUTION_STATUS_FAILED, enums.WORKFLOW_EXECUTION_STATUS_CANCELED, enums.WORKFLOW_EXECUTION_STATUS_TERMINATED, enums.WORKFLOW_EXECUTION_STATUS_TIMED_OUT:
			err = a.Store.Fail(ctx, value.ID)
			if err != nil {
				return err
			}
		}
	}
	return a.Store.PruneReceipts(ctx)
}
func ReconcileWorkspaces(ctx workflow.Context) error {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 2 * time.Minute, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 3}})
	var a *Activities
	if err := workflow.ExecuteActivity(ctx, a.ReconcileWorkspaceAdmissions).Get(ctx, nil); err != nil {
		return err
	}
	var mappings []workspace.Storage
	if err := workflow.ExecuteActivity(ctx, a.UnreleasedProvisioning).Get(ctx, &mappings); err != nil {
		return err
	}
	remote := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{TaskQueue: letfs.Queue, StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 3}})
	for _, mapping := range mappings {
		if err := workflow.ExecuteActivity(remote, letfs.ReleaseProvisioning, provisioned(mapping)).Get(ctx, nil); err != nil {
			return err
		}
		if err := workflow.ExecuteActivity(ctx, a.CompleteWorkspaceCreation, mapping.WorkspaceID).Get(ctx, nil); err != nil {
			return err
		}
	}
	return nil
}
func EnsureReconciliation(ctx context.Context, tc client.Client) error {
	_, err := tc.ScheduleClient().Create(ctx, client.ScheduleOptions{ID: "workspace-reconciliation", Spec: client.ScheduleSpec{Intervals: []client.ScheduleIntervalSpec{{Every: 5 * time.Minute}}}, Action: &client.ScheduleWorkflowAction{ID: "reconcile-workspaces", Workflow: ReconcileWorkspaces, TaskQueue: Queue, WorkflowExecutionTimeout: 4 * time.Minute}, Overlap: enums.SCHEDULE_OVERLAP_POLICY_SKIP, TriggerImmediately: true})
	if errors.Is(err, temporal.ErrScheduleAlreadyRunning) {
		return tc.ScheduleClient().GetHandle(ctx, "workspace-reconciliation").Trigger(ctx, client.ScheduleTriggerOptions{Overlap: enums.SCHEDULE_OVERLAP_POLICY_SKIP})
	}
	return err
}
