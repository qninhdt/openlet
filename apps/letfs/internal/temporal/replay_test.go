//go:build replay

package temporal

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

func TestRecordedFilesystemWorkflows(t *testing.T) {
	dir := os.Getenv("OPENLET_HISTORY_DIR")
	require.NotEmpty(t, dir, "export fresh Go histories with the integration suite first")
	replayer := worker.NewWorkflowReplayer()
	replayer.RegisterWorkflowWithOptions(DeleteScope, workflow.RegisterOptions{Name: DeleteScopeName})
	replayer.RegisterWorkflowWithOptions(DeleteFilesystem, workflow.RegisterOptions{Name: DeleteFilesystemName})
	replayer.RegisterWorkflowWithOptions(ProcessFile, workflow.RegisterOptions{Name: ProcessFileName})
	replayer.RegisterWorkflowWithOptions(StorageMaintenance, workflow.RegisterOptions{Name: StorageMaintenanceName})
	patterns := []string{
		"DeleteFilesystem-0.json", "DeleteScope-0.json",
		"ProcessFile-parsed-0.json", "ProcessFile-failed-0.json", "ProcessFile-retry-0.json", "ProcessFile-index-only-0.json",
		"StorageMaintenance-*.json", "ProcessFilePython-*.json",
	}
	if _, err := os.Stat(filepath.Join(dir, "OnboardUser.json")); err == nil {
		patterns = []string{"DeleteFilesystem.json", "DeleteScope.json",
			"ProcessFileParsed.json", "ProcessFileDirect.json", "ProcessFileFailed.json", "ProcessFileRecovery.json", "StorageMaintenance.json"}
	} else {
		require.True(t, os.IsNotExist(err), "cannot inspect history source: %v", err)
	}
	for _, pattern := range patterns {
		paths, err := filepath.Glob(filepath.Join(dir, pattern))
		require.NoError(t, err)
		require.NotEmpty(t, paths, "missing required history: %s", pattern)
		for _, path := range paths {
			t.Run(filepath.Base(path), func(t *testing.T) {
				require.NoError(t, replayer.ReplayWorkflowHistoryFromJSONFile(nil, path))
			})
		}
	}
}
