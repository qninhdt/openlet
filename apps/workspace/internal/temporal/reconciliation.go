package temporal

import (
	"context"
	"errors"
	"github.com/google/uuid"
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
		id := "create-workspace/" + value.ID.String()
		if value.Status == "deleting" {
			if err = StartDelete(ctx, a.Temporal, a.Store, value.ID); err != nil {
				return err
			}
			continue
		}
		description, err := a.Temporal.DescribeWorkflowExecution(ctx, id, "")
		var missing *serviceerror.NotFound
		if errors.As(err, &missing) {
			err = StartCreate(ctx, a.Temporal, value.ID)
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

type ReconcileInput struct {
	After  uuid.UUID
	Failed bool
}

func (a *Activities) WorkspaceRelationshipIDs(ctx context.Context, after uuid.UUID) ([]uuid.UUID, error) {
	return a.Store.RelationshipIDs(ctx, after)
}

func (a *Activities) CleanupWorkspaceRelationships(ctx context.Context, id uuid.UUID) error {
	return businessError(a.Store.CleanupRelationships(ctx, a.Graph, id))
}

func ReconcileWorkspaces(ctx workflow.Context, in ReconcileInput) error {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 2 * time.Minute, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 3}})
	var a *Activities
	if in.After == uuid.Nil {
		if err := workflow.ExecuteActivity(ctx, a.ReconcileWorkspaceAdmissions).Get(ctx, nil); err != nil {
			if temporal.IsCanceledError(err) {
				return err
			}
			in.Failed = true
			workflow.GetLogger(ctx).Error("workspace admissions reconciliation failed", "error", err)
		}
		var mappings []workspace.Storage
		if err := workflow.ExecuteActivity(ctx, a.UnreleasedProvisioning).Get(ctx, &mappings); err != nil {
			if temporal.IsCanceledError(err) {
				return err
			}
			in.Failed = true
			workflow.GetLogger(ctx).Error("storage release reconciliation failed", "error", err)
		}
		remote := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{TaskQueue: letfs.Queue, StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 3}})
		for _, mapping := range mappings {
			if err := workflow.ExecuteActivity(remote, letfs.ReleaseProvisioning, "workspace", provisioned(mapping)).Get(ctx, nil); err != nil {
				if temporal.IsCanceledError(err) {
					return err
				}
				in.Failed = true
				workflow.GetLogger(ctx).Error("storage release reconciliation failed", "workspace_id", mapping.WorkspaceID.String(), "error", err)
				continue
			}
			if err := workflow.ExecuteActivity(ctx, a.SyncWorkspaceRelationships, mapping.WorkspaceID).Get(ctx, nil); err != nil {
				if temporal.IsCanceledError(err) {
					return err
				}
				in.Failed = true
				workflow.GetLogger(ctx).Error("storage release reconciliation failed", "workspace_id", mapping.WorkspaceID.String(), "error", err)
				continue
			}
			if err := workflow.ExecuteActivity(ctx, a.CompleteWorkspaceCreation, mapping.WorkspaceID).Get(ctx, nil); err != nil {
				if temporal.IsCanceledError(err) {
					return err
				}
				in.Failed = true
				workflow.GetLogger(ctx).Error("storage release reconciliation failed", "workspace_id", mapping.WorkspaceID.String(), "error", err)
				continue
			}
		}
	}

	var ids []uuid.UUID
	if err := workflow.ExecuteActivity(ctx, a.WorkspaceRelationshipIDs, in.After).Get(ctx, &ids); err != nil {
		return err
	}
	for _, id := range ids {
		if err := workflow.ExecuteActivity(ctx, a.SyncWorkspaceRelationships, id).Get(ctx, nil); err != nil {
			if temporal.IsCanceledError(err) {
				return err
			}
			in.Failed = true
			workflow.GetLogger(ctx).Error("workspace relationship reconciliation failed", "workspace_id", id.String(), "error", err)
		}
		if err := workflow.ExecuteActivity(ctx, a.CleanupWorkspaceRelationships, id).Get(ctx, nil); err != nil {
			if temporal.IsCanceledError(err) {
				return err
			}
			in.Failed = true
			workflow.GetLogger(ctx).Error("workspace relationship cleanup failed", "workspace_id", id.String(), "error", err)
		}
		in.After = id
	}
	if len(ids) == 100 {
		return workflow.NewContinueAsNewError(ctx, ReconcileWorkspaces, in)
	}
	if in.Failed {
		return temporal.NewApplicationError("workspace relationships could not all be synchronized", "RELATIONSHIP_SYNC_FAILED")
	}

	return nil
}
func EnsureReconciliation(ctx context.Context, tc client.Client) error {
	_, err := tc.ScheduleClient().Create(ctx, client.ScheduleOptions{ID: "workspace-reconciliation", Spec: client.ScheduleSpec{Intervals: []client.ScheduleIntervalSpec{{Every: 5 * time.Minute}}}, Action: &client.ScheduleWorkflowAction{ID: "reconcile-workspaces", Workflow: ReconcileWorkspaces, TaskQueue: Queue, Args: []interface{}{ReconcileInput{}}}, Overlap: enums.SCHEDULE_OVERLAP_POLICY_SKIP, TriggerImmediately: true})
	if errors.Is(err, temporal.ErrScheduleAlreadyRunning) {
		handle := tc.ScheduleClient().GetHandle(ctx, "workspace-reconciliation")
		if err := handle.Update(ctx, client.ScheduleUpdateOptions{DoUpdate: func(in client.ScheduleUpdateInput) (*client.ScheduleUpdate, error) {
			schedule := in.Description.Schedule
			schedule.Action = &client.ScheduleWorkflowAction{ID: "reconcile-workspaces", Workflow: ReconcileWorkspaces, TaskQueue: Queue, Args: []interface{}{ReconcileInput{}}}
			return &client.ScheduleUpdate{Schedule: &schedule}, nil
		}}); err != nil {
			return err
		}
		return handle.Trigger(ctx, client.ScheduleTriggerOptions{Overlap: enums.SCHEDULE_OVERLAP_POLICY_SKIP})
	}
	return err
}
