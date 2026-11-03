package temporal

import (
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"go.temporal.io/sdk/workflow"
)

const (
	PurgeTrashName       = "PurgeTrash"
	DeleteFilesystemName = "DeleteFilesystem"
)

func deleteNodes(ctx workflow.Context, input filesystem.DeletionInput, name string) (uuid.UUID, error) {
	// Once admitted, cancellation must not strand destructive cleanup.
	ctx, cancel := workflow.NewDisconnectedContext(ctx)
	defer cancel()
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second})
	for range 200 {
		var done bool
		if err := workflow.ExecuteActivity(ctx, "delete_nodes_batch", input).Get(ctx, &done); err != nil {
			return uuid.Nil, err
		}
		if done {
			if input.EntryID != nil {
				return *input.EntryID, nil
			}
			return input.FilesystemID, nil
		}
	}
	return uuid.Nil, workflow.NewContinueAsNewError(ctx, name, input)
}

func PurgeTrash(ctx workflow.Context, input filesystem.DeletionInput) (uuid.UUID, error) {
	return deleteNodes(ctx, input, PurgeTrashName)
}

func DeleteFilesystem(ctx workflow.Context, input filesystem.DeletionInput) (uuid.UUID, error) {
	return deleteNodes(ctx, input, DeleteFilesystemName)
}
