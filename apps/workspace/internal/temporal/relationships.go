package temporal

import (
	"context"
	"time"

	"github.com/google/uuid"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"openlet/apps/workspace/internal/workspace"
)

func SyncWorkspace(ctx workflow.Context, id uuid.UUID) error {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{
		StartToCloseTimeout: 30 * time.Second,
		RetryPolicy:         &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second},
	})
	var a *Activities
	return workflow.ExecuteActivity(ctx, a.SyncWorkspaceRelationships, id).Get(ctx, nil)
}

// Synchronized mutation success waits for durable work; a lost caller cannot cancel it.
func SyncRelationships(ctx context.Context, tc client.Client, store *workspace.Store, id uuid.UUID) error {
	var revision, lifecycle string
	if err := store.DB.QueryRow(ctx, `SELECT revision::text,status FROM workspaces WHERE id=$1`, id).Scan(&revision, &lifecycle); err != nil {
		return err
	}
	start, cancel := context.WithTimeout(ctx, 2*time.Second)
	run, err := tc.ExecuteWorkflow(start, client.StartWorkflowOptions{
		ID: "sync-workspace/" + id.String() + "/" + revision + "/" + lifecycle, TaskQueue: Queue,
		WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING,
		WorkflowIDReusePolicy:    enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE,
		WorkflowExecutionTimeout: 7 * 24 * time.Hour,
	}, SyncWorkspace, id)
	cancel()
	if err != nil {
		return err
	}
	return run.Get(ctx, nil)
}
