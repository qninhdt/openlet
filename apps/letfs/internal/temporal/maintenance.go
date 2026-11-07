package temporal

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	sharedtemporal "github.com/qninhdt/openlet/packages/go/temporal"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	sdktemporal "go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
)

const StorageMaintenanceName = "StorageMaintenance"

func StorageMaintenance(ctx workflow.Context) error {
	short := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &sdktemporal.RetryPolicy{MaximumAttempts: 3}})
	bounded := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 240 * time.Second, HeartbeatTimeout: 30 * time.Second, RetryPolicy: &sdktemporal.RetryPolicy{MaximumAttempts: 3}})
	expiryErr := workflow.ExecuteActivity(short, "ExpireUploads").Get(short, nil)
	recoveryErr := workflow.ExecuteActivity(bounded, "ReconcileResources").Get(bounded, nil)
	cleanupErr := workflow.ExecuteActivity(bounded, "DeleteObjects").Get(bounded, nil)
	return errors.Join(expiryErr, recoveryErr, cleanupErr)
}

func EnsureSchedule(ctx context.Context, tc client.Client) error {
	_, err := tc.ScheduleClient().Create(ctx, client.ScheduleOptions{ID: "openlet-storage-maintenance",
		Spec:    client.ScheduleSpec{Intervals: []client.ScheduleIntervalSpec{{Every: 300 * time.Second}}},
		Action:  &client.ScheduleWorkflowAction{ID: "storage-maintenance", Workflow: StorageMaintenanceName, TaskQueue: Queue},
		Overlap: enums.SCHEDULE_OVERLAP_POLICY_SKIP})
	if errors.Is(err, sdktemporal.ErrScheduleAlreadyRunning) {
		return nil
	}
	return dependencyError(err)
}

func (a *Activities) ExpireUploads(ctx context.Context) (int, error) {
	if err := a.Store.PruneReceipts(ctx); err != nil {
		return 0, sharedtemporal.Error(err)
	}
	count, err := a.Store.ExpireUploads(ctx)
	return count, sharedtemporal.Error(err)
}

func (a *Activities) DeleteObjects(ctx context.Context) (int, error) {
	stop := heartbeat(ctx)
	defer stop()
	count, err := a.Store.DeleteObjects(ctx)
	return count, sharedtemporal.Error(err)
}

func (a *Activities) ReconcileResources(ctx context.Context) (int, error) {
	stop := heartbeat(ctx)
	defer stop()
	count, err := a.reconcileResources(ctx)
	return count, sharedtemporal.Error(err)
}

func (a *Activities) reconcileResources(ctx context.Context) (int, error) {
	count, err := a.Store.DiscardForests(ctx)
	if err != nil {
		return count, err
	}
	rows, err := a.Store.DB.Query(ctx, `SELECT id FROM filesystems WHERE state='deleting' ORDER BY id LIMIT 64`)
	if err != nil {
		return count, err
	}
	deleting, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return count, err
	}
	for _, id := range deleting {
		if err = a.Jobs.StartDeletion(ctx, filesystem.DeletionInput{FilesystemID: id}); err != nil {
			return count, err
		}
	}
	rows, err = a.Store.DB.Query(ctx, `SELECT sc.filesystem_id,sc.id FROM scopes sc JOIN filesystems fs ON fs.id=sc.filesystem_id WHERE sc.state='deleting' AND fs.state='active' ORDER BY sc.id LIMIT 64`)
	if err != nil {
		return count, err
	}
	scopes, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (filesystem.DeletionInput, error) {
		var in filesystem.DeletionInput
		err := row.Scan(&in.FilesystemID, &in.ScopeID)
		return in, err
	})
	if err != nil {
		return count, err
	}
	for _, scope := range scopes {
		if err = a.Jobs.StartDeletion(ctx, scope); err != nil {
			return count, err
		}
	}
	candidates, err := a.Store.ProcessingCandidates(ctx)
	if err != nil {
		return count, err
	}
	for _, candidate := range candidates {
		running, err := a.Jobs.WorkflowStatus(ctx, candidate.Source.WorkflowID(), &candidate.UpdatedAt)
		if err != nil {
			return count, err
		}
		if running != nil && *running {
			continue
		}
		dispatch, err := a.Store.ReconcileProcessing(ctx, candidate, running != nil)
		if err != nil {
			return count, err
		}
		if dispatch {
			if err = a.Jobs.StartProcessing(ctx, candidate); err != nil {
				return count, err
			}
		}
		count++
	}
	if cleaned, err := a.cleanupIndexes(ctx); err != nil {
		slog.WarnContext(ctx, "search index cleanup deferred")
	} else {
		count += cleaned
	}
	return count, nil
}

func (a *Activities) cleanupIndexes(ctx context.Context) (int, error) {
	items, err := a.Store.IndexDeletionCandidates(ctx)
	if err != nil {
		return 0, err
	}
	deadline := time.Now().Add(30 * time.Second)
	count := 0
	for _, item := range items {
		if !time.Now().Before(deadline) {
			break
		}
		running, err := a.Jobs.WorkflowStatus(ctx, item.Source.WorkflowID(), nil)
		if err != nil {
			return count, err
		}
		if running != nil && *running {
			continue
		}
		deleted, err := a.Store.DeleteObsoleteIndex(ctx, item)
		if err != nil {
			return count, err
		}
		if deleted {
			count++
		}
	}
	return count, nil
}
