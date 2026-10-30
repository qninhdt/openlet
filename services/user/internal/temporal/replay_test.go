//go:build replay

package temporal

import (
	"go.temporal.io/sdk/worker"
	"os"
	"path/filepath"
	"testing"
)

func TestRecordedUserWorkflow(t *testing.T) {
	replayer := worker.NewWorkflowReplayer()
	replayer.RegisterWorkflow(OnboardUser)
	if e := replayer.ReplayWorkflowHistoryFromJSONFile(nil, filepath.Join(os.Getenv("OPENLET_HISTORY_DIR"), "OnboardUser.json")); e != nil {
		t.Fatal(e)
	}
}
