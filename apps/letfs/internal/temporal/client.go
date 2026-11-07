package temporal

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/packages/go/apperr"
	sharedtemporal "github.com/qninhdt/openlet/packages/go/temporal"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
)

type Jobs struct{ Client client.Client }

func dependencyError(err error) error {
	if err == nil {
		return nil
	}
	return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "Temporal unavailable")
}

func copyWorkflowID(fs, id uuid.UUID) string { return "copy/" + fs.String() + "/" + id.String() }

func (j *Jobs) StartCopy(ctx context.Context, admission filesystem.CopyAdmission) error {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	_, err := j.Client.ExecuteWorkflow(ctx, client.StartWorkflowOptions{
		ID: copyWorkflowID(admission.FilesystemID, admission.ID), TaskQueue: Queue,
		WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING,
		WorkflowIDReusePolicy:    enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE,
		WorkflowExecutionTimeout: time.Hour,
	}, CopyTreeName, admission)
	return dependencyError(err)
}

func (j *Jobs) StartDeletion(ctx context.Context, input filesystem.DeletionInput) error {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	name := DeleteFilesystemName
	var payload any = sharedtemporal.FilesystemDeletion{FilesystemID: input.FilesystemID}
	if input.ScopeID != uuid.Nil && input.EntryID == nil {
		name = DeleteScopeName
		payload = sharedtemporal.ScopeDeletion{FilesystemID: input.FilesystemID, ScopeID: input.ScopeID}
	}
	if input.EntryID != nil {
		name = PurgeTrashName
		payload = input
	}
	_, err := j.Client.ExecuteWorkflow(ctx, client.StartWorkflowOptions{
		TaskQueue:                Queue,
		WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING,
		WorkflowIDReusePolicy:    enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE,
		WorkflowExecutionTimeout: 7 * 24 * time.Hour,
	}, name, payload)
	return dependencyError(err)
}
