//go:build replay

package temporal

import (
	historypb "go.temporal.io/api/history/v1"
	"go.temporal.io/sdk/worker"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"
	"os"
	"path/filepath"
	"testing"
)

func TestRecordedWorkspaceWorkflows(t *testing.T) {
	replayer := worker.NewWorkflowReplayer()
	replayer.RegisterWorkflow(CreateWorkspace)
	replayer.RegisterWorkflow(DeleteWorkspace)
	for _, name := range []string{"CreateWorkspace", "DeleteWorkspace"} {
		if e := replayer.ReplayWorkflowHistoryFromJSONFile(nil, filepath.Join(os.Getenv("OPENLET_HISTORY_DIR"), name+".json")); e != nil {
			t.Fatal(e)
		}
	}
	exportRustHistory(t, "DeleteFilesystem")
}

func TestRustHistoryExports(t *testing.T) {
	for _, name := range []string{"CopyNode", "CopyNodeContinued", "CopyNodeRecovery", "PurgeTrash", "StorageMaintenance", "ProcessFileParsed", "ProcessFileDirect", "ProcessFileFailed", "ProcessFileRecovery"} {
		exportRustHistory(t, name)
	}
}

// Rust consumes protobuf histories; the CLI exports the official protobuf JSON representation.
func exportRustHistory(t *testing.T, name string) {
	t.Helper()
	child, err := os.ReadFile(filepath.Join(os.Getenv("OPENLET_HISTORY_DIR"), name+".json"))
	if err != nil {
		t.Fatal(err)
	}
	var history historypb.History
	if err = protojson.Unmarshal(child, &history); err != nil {
		t.Fatal(err)
	}
	encoded, err := proto.Marshal(&history)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(os.Getenv("OPENLET_HISTORY_DIR"), name+".bin"), encoded, 0600); err != nil {
		t.Fatal(err)
	}
}
