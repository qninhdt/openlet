package temporal

import (
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

func Register(registry worker.Registry, activities *Activities) {
	registry.RegisterWorkflowWithOptions(CopyTree, workflow.RegisterOptions{Name: CopyTreeName})
	registry.RegisterWorkflowWithOptions(ProcessFile, workflow.RegisterOptions{Name: ProcessFileName})
	registry.RegisterWorkflowWithOptions(PurgeTrash, workflow.RegisterOptions{Name: PurgeTrashName})
	registry.RegisterWorkflowWithOptions(DeleteScope, workflow.RegisterOptions{Name: DeleteScopeName})
	registry.RegisterWorkflowWithOptions(DeleteFilesystem, workflow.RegisterOptions{Name: DeleteFilesystemName})
	registry.RegisterWorkflowWithOptions(StorageMaintenance, workflow.RegisterOptions{Name: StorageMaintenanceName})
	registry.RegisterActivity(activities)
}
