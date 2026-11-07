//go:build replay

package temporal

import (
	"go.temporal.io/sdk/worker"
	"os"
	"path/filepath"
	"testing"
)

func TestRecordedWorkspaceWorkflows(t *testing.T) {
	replayer := worker.NewWorkflowReplayer()
	replayer.RegisterWorkflow((&Workflows{}).CreateWorkspace)
	replayer.RegisterWorkflow(DeleteWorkspace)
	replayer.RegisterWorkflow(WorkspaceChanges)
	replayer.RegisterWorkflow(WorkspaceMaintenance)
	for _, name := range []string{"CreateWorkspace", "DeleteWorkspace", "WorkspaceChanges", "WorkspaceMaintenance"} {
		if e := replayer.ReplayWorkflowHistoryFromJSONFile(nil, filepath.Join(os.Getenv("OPENLET_HISTORY_DIR"), name+".json")); e != nil {
			t.Fatal(e)
		}
	}
}
