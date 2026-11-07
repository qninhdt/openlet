package temporal

import (
	"time"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
)

const (
	Queue           = "openlet-letfs"
	CPUQueue        = "openlet-letfs-cpu"
	IOQueue         = "openlet-letfs-io"
	ProcessFileName = "ProcessFile"
)

type ProcessFileInput struct {
	Source             filesystem.Generation `json:"source"`
	ParseRequired      bool                  `json:"parse_required"`
	EnrichmentRequired bool                  `json:"enrichment_required"`
	SkipIndex          bool                  `json:"skip_index"`
}

func ProcessFile(ctx workflow.Context, input ProcessFileInput) (filesystem.Generation, error) {
	options := workflow.ActivityOptions{TaskQueue: IOQueue, ScheduleToCloseTimeout: 2 * time.Hour, StartToCloseTimeout: 30 * time.Minute,
		HeartbeatTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 3}}
	io := workflow.WithActivityOptions(ctx, options)
	if input.ParseRequired {
		options.TaskQueue = CPUQueue
		cpu := workflow.WithActivityOptions(ctx, options)
		if err := workflow.ExecuteActivity(cpu, "process_file", input.Source).Get(cpu, nil); err != nil {
			return filesystem.Generation{}, err
		}
	}
	if input.EnrichmentRequired {
		if err := workflow.ExecuteActivity(io, "enrich_file", input.Source).Get(io, nil); err != nil {
			return filesystem.Generation{}, err
		}
	}
	if input.SkipIndex {
		return input.Source, nil
	}
	var result filesystem.Generation
	err := workflow.ExecuteActivity(io, "index_file", input.Source).Get(io, &result)
	return result, err
}
