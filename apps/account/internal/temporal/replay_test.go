//go:build replay

package temporal

import (
	"go.temporal.io/sdk/worker"
	"os"
	"path/filepath"
	"testing"
)

func TestRecordedAccountWorkflows(t *testing.T) {
	replayer := worker.NewWorkflowReplayer()
	replayer.RegisterWorkflow(OnboardUser)
	for _, name := range []string{"OnboardUser"} {
		if e := replayer.ReplayWorkflowHistoryFromJSONFile(nil, filepath.Join(os.Getenv("OPENLET_HISTORY_DIR"), name+".json")); e != nil {
			t.Fatal(e)
		}
	}
}
