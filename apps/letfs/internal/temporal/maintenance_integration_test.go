//go:build integration

package temporal

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"
	"openlet/apps/letfs/internal/filesystem"
	"openlet/apps/letfs/internal/testfixture"
	"openlet/packages/go/identity"
)

func TestIntegrationMaintenanceRecoversDispatchAndReplays(t *testing.T) {
	tc, _ := testfixture.Temporal(t)
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	s := &filesystem.Store{DB: db, MaxNodes: 100, ProcessingMaxOutputs: 10, IndexSpace: filesystem.VectorSpace{Model: "embedding", Collection: "files", Dimension: 8}}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	bucket, fs, file := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateBucket(owner, uuid.New(), filesystem.CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'notes.txt','file',1)`, file, fs, created.RootID)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_actor_id,processing_format,processing_source_identity,publication_status,index_status)
 VALUES($1,'inline','x',1,$2,'text','inline:2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881','parsed','pending')`, file, uuid.New())
	require.NoError(t, err)
	jobs := &Jobs{Client: tc}
	w := worker.New(tc, Queue, worker.Options{WorkerStopTimeout: time.Second})
	Register(w, &Activities{Store: s, Jobs: jobs})
	require.NoError(t, w.Start())
	t.Cleanup(w.Stop)
	ctx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
	defer cancel()
	missing, err := jobs.WorkflowStatus(ctx, "missing-workflow", nil)
	require.NoError(t, err)
	require.Nil(t, missing)
	for range 2 {
		require.NoError(t, EnsureSchedule(ctx, tc))
	}
	schedule := tc.ScheduleClient().GetHandle(ctx, "openlet-storage-maintenance")
	t.Cleanup(func() {
		cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		require.NoError(t, schedule.Delete(cleanup))
	})
	description, err := schedule.Describe(ctx)
	require.NoError(t, err)
	require.Equal(t, 300*time.Second, description.Schedule.Spec.Intervals[0].Every)
	require.Equal(t, enums.SCHEDULE_OVERLAP_POLICY_SKIP, description.Schedule.Policy.Overlap)
	runMaintenance := func() {
		t.Helper()
		run, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "maintenance-test/" + uuid.NewString(), TaskQueue: Queue}, StorageMaintenanceName)
		require.NoError(t, err)
		require.NoError(t, run.Get(ctx, nil))
		var stages []string
		iterator := tc.GetWorkflowHistory(ctx, run.GetID(), run.GetRunID(), false, enums.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
		for iterator.HasNext() {
			event, err := iterator.Next()
			require.NoError(t, err)
			if scheduled := event.GetActivityTaskScheduledEventAttributes(); scheduled != nil {
				stages = append(stages, scheduled.ActivityType.Name)
				require.EqualValues(t, 3, scheduled.RetryPolicy.MaximumAttempts)
				if scheduled.ActivityType.Name == "expire_uploads_batch" {
					require.Equal(t, 30*time.Second, scheduled.StartToCloseTimeout.AsDuration())
				} else {
					require.Equal(t, 240*time.Second, scheduled.StartToCloseTimeout.AsDuration())
					require.Equal(t, 30*time.Second, scheduled.HeartbeatTimeout.AsDuration())
				}
			}
		}
		require.Equal(t, []string{"expire_uploads_batch", "reconcile_resources_batch", "delete_objects_batch"}, stages)
		require.Equal(t, 1, replayRuns(t, tc, run.GetID(), run.GetRunID(), "StorageMaintenance-"+uuid.NewString()))
	}
	runMaintenance()
	source := filesystem.Generation{FileID: file, Generation: 1}
	running, err := jobs.WorkflowStatus(ctx, source.WorkflowID(), nil)
	require.NoError(t, err)
	require.NotNil(t, running, "maintenance dispatches the committed intent without a client retry")
	require.True(t, *running)
	info, err := tc.DescribeWorkflowExecution(ctx, source.WorkflowID(), "")
	require.NoError(t, err)
	firstRun := info.WorkflowExecutionInfo.Execution.RunId
	pending, err := s.PendingProcessing(ctx, file)
	require.NoError(t, err)
	require.NoError(t, jobs.StartProcessing(ctx, pending, s.IndexSpace))
	info, err = tc.DescribeWorkflowExecution(ctx, source.WorkflowID(), "")
	require.NoError(t, err)
	require.Equal(t, firstRun, info.WorkflowExecutionInfo.Execution.RunId, "retries reuse the active processing run")
	require.NoError(t, tc.TerminateWorkflow(ctx, source.WorkflowID(), firstRun, "isolated failure"))
	runMaintenance()
	var publication, index, code string
	require.NoError(t, db.QueryRow(ctx, `SELECT publication_status,index_status,processing_error FROM files WHERE node_id=$1`, file).Scan(&publication, &index, &code))
	require.Equal(t, "failed", publication)
	require.Equal(t, "failed", index)
	require.Equal(t, "PROCESSING_FAILED", code)
	future := time.Now().Add(time.Minute)
	running, err = jobs.WorkflowStatus(ctx, source.WorkflowID(), &future)
	require.NoError(t, err)
	require.Nil(t, running, "closed histories older than a new admission cannot fail it")
}
