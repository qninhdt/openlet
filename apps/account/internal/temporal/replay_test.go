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
	replayer.RegisterWorkflow(ReconcileAccounts)
	for _, name := range []string{"OnboardUser", "ReconcileAccounts"} {
		if e := replayer.ReplayWorkflowHistoryFromJSONFile(nil, filepath.Join(os.Getenv("OPENLET_HISTORY_DIR"), name+".json")); e != nil {
			t.Fatal(e)
		}
	}
}
