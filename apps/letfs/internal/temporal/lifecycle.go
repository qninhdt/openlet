package temporal

import (
	"github.com/google/uuid"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/workflow"
	"time"
)

const (
	DeleteFilesystemName = shared.DeleteFilesystemWorkflow
	DeleteScopeName      = shared.DeleteScopeWorkflow
)

func bulkContext(ctx workflow.Context) workflow.Context {
	return workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 24 * time.Hour, HeartbeatTimeout: 30 * time.Second})
}
func DeleteScope(ctx workflow.Context, in shared.ScopeDeletion) error {
	ctx, cancel := workflow.NewDisconnectedContext(ctx)
	defer cancel()
	ctx = bulkContext(ctx)
	return workflow.ExecuteActivity(ctx, "DeleteScopeData", in).Get(ctx, nil)
}
func DeleteFilesystem(ctx workflow.Context, in shared.FilesystemDeletion) error {
	ctx, cancel := workflow.NewDisconnectedContext(ctx)
	defer cancel()
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second})
	for page := 0; page < 100; page++ {
		var scopes []uuid.UUID
		if err := workflow.ExecuteActivity(ctx, "ListScopesForDeletion", in).Get(ctx, &scopes); err != nil {
			return err
		}
		if len(scopes) == 0 {
			return workflow.ExecuteActivity(ctx, "RemoveFilesystem", in.FilesystemID).Get(ctx, nil)
		}
		child := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{TaskQueue: shared.LetFSQueue, ParentClosePolicy: enums.PARENT_CLOSE_POLICY_ABANDON})
		for first := 0; first < len(scopes); first += 4 {
			futures := make([]workflow.ChildWorkflowFuture, 0, 4)
			for _, scope := range scopes[first:min(first+4, len(scopes))] {
				futures = append(futures, workflow.ExecuteChildWorkflow(child, DeleteScopeName, shared.ScopeDeletion{FilesystemID: in.FilesystemID, ScopeID: scope}))
			}
			for _, future := range futures {
				if err := future.Get(ctx, nil); err != nil {
					return err
				}
			}
		}
		in.After = scopes[len(scopes)-1]
	}
	return workflow.NewContinueAsNewError(ctx, DeleteFilesystem, in)
}
