//go:build workflow

package temporal

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
)

func TestProcessFileRunsRequiredStagesOnTheirQueues(t *testing.T) {
	for _, scenario := range []struct {
		name          string
		parse, enrich bool
		skipIndex     bool
		fail          string
		want          []string
	}{
		{name: "parse and enrich", parse: true, enrich: true, want: []string{"process_file", "enrich_file", "index_file"}},
		{name: "enrich only", enrich: true, want: []string{"enrich_file", "index_file"}},
		{name: "index only", want: []string{"index_file"}},
		{name: "indexing disabled", parse: true, enrich: true, skipIndex: true, want: []string{"process_file", "enrich_file"}},
		{name: "parse failure", parse: true, enrich: true, fail: "process_file", want: []string{"process_file"}},
		{name: "enrichment failure", parse: true, enrich: true, fail: "enrich_file", want: []string{"process_file", "enrich_file"}},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			var suite testsuite.WorkflowTestSuite
			env := suite.NewTestWorkflowEnvironment()
			source := filesystem.Generation{FileID: uuid.New(), Generation: 7}
			var calls []string
			for _, name := range []string{"process_file", "enrich_file", "index_file"} {
				env.RegisterActivityWithOptions(func(ctx context.Context, input filesystem.Generation) (filesystem.Generation, error) {
					require.Equal(t, source, input)
					info := activity.GetInfo(ctx)
					expected := IOQueue
					if name == "process_file" {
						expected = CPUQueue
					}
					require.Equal(t, expected, info.TaskQueue)
					require.Equal(t, 30*time.Second, info.HeartbeatTimeout)
					calls = append(calls, name)
					if name == scenario.fail {
						return filesystem.Generation{}, temporal.NewNonRetryableApplicationError("rejected generation", "SOURCE_REPLACED", nil)
					}
					return input, nil
				}, activity.RegisterOptions{Name: name})
			}
			env.ExecuteWorkflow(ProcessFile, ProcessFileInput{Source: source, ParseRequired: scenario.parse, EnrichmentRequired: scenario.enrich, SkipIndex: scenario.skipIndex})
			require.Equal(t, scenario.want, calls)
			if scenario.fail != "" {
				require.Error(t, env.GetWorkflowError())
				return
			}
			require.NoError(t, env.GetWorkflowError())
			var result filesystem.Generation
			require.NoError(t, env.GetWorkflowResult(&result))
			require.Equal(t, source, result)
		})
	}
}
