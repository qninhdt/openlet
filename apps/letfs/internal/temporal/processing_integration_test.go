//go:build integration

package temporal

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	sdktemporal "go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/worker"
	"openlet/apps/letfs/internal/filesystem"
	"openlet/apps/letfs/internal/testfixture"
)

func TestIntegrationProcessingQueuesRetriesFailuresAndReplay(t *testing.T) {
	tc, _ := testfixture.Temporal(t)
	owner := worker.New(tc, Queue, worker.Options{WorkerStopTimeout: time.Second})
	Register(owner, &Activities{})
	cpu := worker.New(tc, CPUQueue, worker.Options{WorkerStopTimeout: time.Second})
	io := worker.New(tc, IOQueue, worker.Options{WorkerStopTimeout: time.Second})
	for _, stage := range []string{"process_file", "enrich_file", "index_file"} {
		w := io
		if stage == "process_file" {
			w = cpu
		}
		w.RegisterActivityWithOptions(func(ctx context.Context, in filesystem.Generation) (filesystem.Generation, error) {
			activity.RecordHeartbeat(ctx)
			if stage == "process_file" {
				if in.Generation == 2 {
					return filesystem.Generation{}, sdktemporal.NewNonRetryableApplicationError("source changed", "SOURCE_REPLACED", nil)
				}
				if in.Generation == 3 && activity.GetInfo(ctx).Attempt == 1 {
					return filesystem.Generation{}, sdktemporal.NewApplicationError("temporary provider failure", "DEPENDENCY_UNAVAILABLE")
				}
			}
			return in, nil
		}, activity.RegisterOptions{Name: stage})
	}
	for _, w := range []worker.Worker{owner, cpu, io} {
		require.NoError(t, w.Start())
		t.Cleanup(w.Stop)
	}
	for _, scenario := range []struct {
		name          string
		generation    int64
		parse, enrich bool
		stages        []string
	}{
		{"parsed", 1, true, true, []string{"process_file", "enrich_file", "index_file"}},
		{"failed", 2, true, true, []string{"process_file"}},
		{"retry", 3, true, true, []string{"process_file", "enrich_file", "index_file"}},
		{"index-only", 4, false, false, []string{"index_file"}},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(t.Context(), 20*time.Second)
			defer cancel()
			source := filesystem.Generation{FileID: uuid.New(), Generation: scenario.generation}
			run, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "process-test/" + source.FileID.String(), TaskQueue: Queue, WorkflowExecutionTimeout: 22500 * time.Second},
				ProcessFileName, ProcessFileInput{Source: source, ParseRequired: scenario.parse, EnrichmentRequired: scenario.enrich})
			require.NoError(t, err)
			var result filesystem.Generation
			err = run.Get(ctx, &result)
			if scenario.generation == 2 {
				var application *sdktemporal.ApplicationError
				require.ErrorAs(t, err, &application)
				require.Equal(t, "SOURCE_REPLACED", application.Type())
			} else {
				require.NoError(t, err)
				require.Equal(t, source, result)
			}
			var stages []string
			var attempts []int32
			iterator := tc.GetWorkflowHistory(ctx, run.GetID(), run.GetRunID(), false, enums.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
			for iterator.HasNext() {
				event, err := iterator.Next()
				require.NoError(t, err)
				if scheduled := event.GetActivityTaskScheduledEventAttributes(); scheduled != nil {
					stages = append(stages, scheduled.ActivityType.Name)
					queue := IOQueue
					if scheduled.ActivityType.Name == "process_file" {
						queue = CPUQueue
					}
					require.Equal(t, queue, scheduled.TaskQueue.Name)
					require.Equal(t, 2*time.Hour, scheduled.ScheduleToCloseTimeout.AsDuration())
					require.Equal(t, 30*time.Minute, scheduled.StartToCloseTimeout.AsDuration())
					require.Equal(t, 30*time.Second, scheduled.HeartbeatTimeout.AsDuration())
					require.EqualValues(t, 3, scheduled.RetryPolicy.MaximumAttempts)
				}
				if started := event.GetActivityTaskStartedEventAttributes(); started != nil {
					attempts = append(attempts, started.Attempt)
				}
			}
			require.Equal(t, scenario.stages, stages)
			if scenario.generation == 3 {
				require.Equal(t, []int32{2, 1, 1}, attempts)
			}
			require.Equal(t, 1, replayRuns(t, tc, run.GetID(), run.GetRunID(), "ProcessFile-"+scenario.name))
		})
	}
}
