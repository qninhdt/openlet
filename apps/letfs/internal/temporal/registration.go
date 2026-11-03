package temporal

import (
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

func Register(registry worker.Registry, activities *Activities) {
	registry.RegisterWorkflowWithOptions(CopyNode, workflow.RegisterOptions{Name: CopyNodeName})
	registry.RegisterWorkflowWithOptions(ProcessFile, workflow.RegisterOptions{Name: ProcessFileName})
	registry.RegisterWorkflowWithOptions(PurgeTrash, workflow.RegisterOptions{Name: PurgeTrashName})
	registry.RegisterWorkflowWithOptions(DeleteFilesystem, workflow.RegisterOptions{Name: DeleteFilesystemName})
	registry.RegisterWorkflowWithOptions(StorageMaintenance, workflow.RegisterOptions{Name: StorageMaintenanceName})
	registry.RegisterActivityWithOptions(activities.ExpireUploads, activity.RegisterOptions{Name: "expire_uploads_batch"})
	registry.RegisterActivityWithOptions(activities.ReconcileResources, activity.RegisterOptions{Name: "reconcile_resources_batch"})
	registry.RegisterActivityWithOptions(activities.DeleteObjects, activity.RegisterOptions{Name: "delete_objects_batch"})
	registry.RegisterActivityWithOptions(activities.CopyItem, activity.RegisterOptions{Name: "copy_item"})
	registry.RegisterActivityWithOptions(activities.NextCopyItem, activity.RegisterOptions{Name: "next_copy_item"})
	registry.RegisterActivityWithOptions(activities.FinishCopyFile, activity.RegisterOptions{Name: "finish_copy_file"})
	registry.RegisterActivityWithOptions(activities.CompleteCopy, activity.RegisterOptions{Name: "complete_copy"})
	registry.RegisterActivityWithOptions(activities.DeleteNodesBatch, activity.RegisterOptions{Name: "delete_nodes_batch"})
}
