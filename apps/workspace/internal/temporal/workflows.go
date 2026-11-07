package temporal

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"time"
)

const Queue = shared.WorkspaceQueue

type Activities struct{ Service *workspace.Service }
type Workflows struct{ QuotaLimit int64 }

func (a *Activities) SaveWorkspace(ctx context.Context, in workspace.Creation) (workspace.Workspace, error) {
	value, err := a.Service.SaveWorkspace(ctx, in)
	return value, shared.Error(err)
}
func (w *Workflows) CreateWorkspace(ctx workflow.Context, in shared.WorkspaceCreation) (value workspace.Workspace, err error) {
	if in.ActorID == uuid.Nil || in.Key == uuid.Nil {
		return value, temporal.NewNonRetryableApplicationError("invalid creation", "VALIDATION", nil)
	}
	if err = workspace.ValidateName(in.Name); err != nil {
		return value, shared.Error(err)
	}
	var allocated struct {
		Creation   workspace.Creation
		LimitBytes int64
	}
	err = workflow.SideEffect(ctx, func(workflow.Context) any {
		return struct {
			Creation   workspace.Creation
			LimitBytes int64
		}{workspace.Creation{Input: in, ID: uuid.Must(uuid.NewV7()), FilesystemID: uuid.Must(uuid.NewV7()), SharedScopeID: uuid.Must(uuid.NewV7()), PersonalScopeID: uuid.Must(uuid.NewV7())}, w.QuotaLimit}
	}).Get(&allocated)
	if err != nil {
		return value, err
	}
	mapping := allocated.Creation
	remote := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{TaskQueue: shared.LetFSQueue, StartToCloseTimeout: 30 * time.Second})
	local := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second})
	storageCreated := false
	defer func() {
		var application *temporal.ApplicationError
		// Only an acknowledged permanent refusal can compensate. SQL/graph uncertainty retries.
		if !storageCreated || err == nil || !errors.As(err, &application) || !application.NonRetryable() {
			return
		}
		cleanup, cancel := workflow.NewDisconnectedContext(ctx)
		defer cancel()
		child := workflow.WithChildOptions(cleanup, workflow.ChildWorkflowOptions{TaskQueue: shared.LetFSQueue, ParentClosePolicy: enums.PARENT_CLOSE_POLICY_ABANDON})
		if cleanupErr := workflow.ExecuteChildWorkflow(child, shared.DeleteFilesystemWorkflow, shared.FilesystemDeletion{FilesystemID: mapping.FilesystemID}).Get(cleanup, nil); cleanupErr != nil {
			err = cleanupErr
		}
	}()
	if err = workflow.ExecuteActivity(remote, shared.CreateFilesystemActivity, shared.FilesystemCreation{ID: mapping.FilesystemID, Key: in.Key, LimitBytes: allocated.LimitBytes}).Get(remote, nil); err != nil {
		return value, err
	}
	storageCreated = true
	if err = workflow.ExecuteActivity(remote, shared.CreateScopesActivity, shared.ScopesCreation{AllowBlobFiles: true, AllowIndexing: true, FilesystemID: mapping.FilesystemID, Key: in.Key, IDs: []uuid.UUID{mapping.SharedScopeID, mapping.PersonalScopeID}}).Get(remote, nil); err != nil {
		return value, err
	}
	var a *Activities
	err = workflow.ExecuteActivity(local, a.SaveWorkspace, mapping).Get(local, &value)
	return value, err
}
func StartCreate(ctx context.Context, tc client.Client, in workspace.CreateInput) (workspace.Workspace, error) {
	run, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "create-workspace/" + in.ActorID.String() + "/" + in.Key.String(), TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, shared.CreateWorkspaceWorkflow, in)
	if err != nil {
		return workspace.Workspace{}, err
	}
	var value workspace.Workspace
	err = run.Get(ctx, &value)
	return value, startError(err)
}
func startError(err error) error {
	if err == nil {
		return nil
	}
	var application *temporal.ApplicationError
	if errors.As(err, &application) && application.NonRetryable() {
		return workspace.Fault{Code: application.Type()}
	}
	if temporal.IsCanceledError(err) {
		return context.Canceled
	}
	return err
}
