package temporal

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"time"
)

type Mutation struct {
	Kind           string
	WorkspaceID    uuid.UUID
	ActorID        uuid.UUID
	TargetID       uuid.UUID
	Key            uuid.UUID
	Revision       string
	Role           string
	Remove         bool
	Update         workspace.UpdateInput
	InvitationHash [32]byte
}
type PreparedMutation struct {
	Command       Mutation
	PreviousOwner uuid.UUID
}

func (a *Activities) PrepareMutation(ctx context.Context, in Mutation) (PreparedMutation, error) {
	out := PreparedMutation{Command: in}
	if in.WorkspaceID == uuid.Nil || in.ActorID == uuid.Nil || in.Key == uuid.Nil {
		return out, businessError(workspace.Fault{Code: "VALIDATION"})
	}
	switch in.Kind {
	case "member", "invite":
	case "update":
		if in.Update.OwnerID == nil {
			return out, businessError(workspace.Fault{Code: "VALIDATION"})
		}
		if err := a.Store.DB.QueryRow(ctx, `SELECT user_id FROM workspace_members WHERE workspace_id=$1 AND role='owner'`, in.WorkspaceID).Scan(&out.PreviousOwner); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return out, businessError(workspace.Fault{Code: "NOT_FOUND"})
			}
			return out, err
		}
	default:
		return out, businessError(workspace.Fault{Code: "VALIDATION"})
	}
	return out, nil
}

func (a *Activities) ApplyMutation(ctx context.Context, in PreparedMutation) (workspace.Workspace, error) {
	cmd := in.Command
	receipt := workspace.MutationReceipt{Key: cmd.Key, Hash: workspace.Fingerprint(in)}
	applied, err := a.Store.MutationApplied(ctx, cmd.ActorID, cmd.WorkspaceID, receipt)
	if err != nil {
		return workspace.Workspace{}, businessError(err)
	}
	if !applied {
		switch cmd.Kind {
		case "member":
			err = a.Store.ChangeMember(ctx, cmd.WorkspaceID, cmd.ActorID, cmd.TargetID, cmd.Role, cmd.Remove, cmd.Revision, receipt)
		case "update":
			_, err = a.Store.Update(ctx, cmd.WorkspaceID, cmd.ActorID, cmd.Revision, cmd.Update, receipt)
		case "invite":
			var emails []string
			emails, err = a.User.VerifiedEmails(ctx, cmd.ActorID)
			if err == nil {
				_, err = a.Store.AcceptInvite(ctx, cmd.ActorID, cmd.InvitationHash, emails, receipt)
			}
		}
		if err != nil {
			// A commit can succeed even when its acknowledgement is lost.
			applied, checkErr := a.Store.MutationApplied(ctx, cmd.ActorID, cmd.WorkspaceID, receipt)
			if checkErr != nil {
				return workspace.Workspace{}, businessError(checkErr)
			}
			if !applied {
				return workspace.Workspace{}, businessError(err)
			}
		}
	}
	affected := []uuid.UUID{cmd.TargetID}
	if cmd.Kind == "update" {
		affected = []uuid.UUID{in.PreviousOwner, *cmd.Update.OwnerID}
	}
	if cmd.Kind == "invite" {
		affected = []uuid.UUID{cmd.ActorID}
	}
	if err = a.Store.WriteMemberRelationships(ctx, a.Graph, cmd.WorkspaceID, affected...); err != nil {
		return workspace.Workspace{}, err
	}
	if err = a.Store.CompleteMutation(ctx, cmd.ActorID, receipt); err != nil {
		return workspace.Workspace{}, err
	}
	if cmd.Kind == "member" && cmd.Remove && cmd.TargetID == cmd.ActorID {
		return workspace.Workspace{ID: cmd.WorkspaceID}, nil
	}
	value, err := a.Store.Get(ctx, cmd.WorkspaceID, cmd.ActorID)
	return value, businessError(err)
}

// WorkspacePermissions serializes business mutations and their graph effects across worker instances.
func WorkspacePermissions(ctx workflow.Context, id uuid.UUID) error {
	activityOptions := workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}}
	mutex := workflow.NewMutex(ctx)
	completed := 0
	if err := workflow.SetUpdateHandler(ctx, "mutate", func(ctx workflow.Context, in Mutation) (workspace.Workspace, error) {
		ctx = workflow.WithActivityOptions(ctx, activityOptions)
		if in.WorkspaceID != id {
			return workspace.Workspace{}, temporal.NewNonRetryableApplicationError("scope mismatch", "VALIDATION", nil)
		}
		if err := mutex.Lock(ctx); err != nil {
			return workspace.Workspace{}, err
		}
		defer mutex.Unlock()
		defer func() { completed++ }()
		var a *Activities
		if in.Kind == "delete" {
			var value workspace.Workspace
			if err := workflow.ExecuteActivity(ctx, a.PrepareWorkspaceDeletion, workspace.DeleteInput{ActorID: in.ActorID, WorkspaceID: id, Revision: in.Revision}).Get(ctx, &value); err != nil {
				return value, err
			}
			if value.Status == "deleted" {
				return value, nil
			}
			child := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{WorkflowID: "delete-workspace/" + id.String(), TaskQueue: Queue, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE, ParentClosePolicy: enums.PARENT_CLOSE_POLICY_ABANDON, WorkflowExecutionTimeout: 7 * 24 * time.Hour})
			if err := workflow.ExecuteChildWorkflow(child, DeleteWorkspace, DeleteWorkflowInput{Workspace: value}).GetChildWorkflowExecution().Get(child, nil); err != nil && !temporal.IsWorkflowExecutionAlreadyStartedError(err) {
				return value, err
			}
			return value, nil
		}
		var prepared PreparedMutation
		local := workflow.WithLocalActivityOptions(ctx, workflow.LocalActivityOptions{StartToCloseTimeout: 5 * time.Second, RetryPolicy: activityOptions.RetryPolicy})
		if err := workflow.ExecuteLocalActivity(local, a.PrepareMutation, in).Get(ctx, &prepared); err != nil {
			return workspace.Workspace{}, err
		}
		var value workspace.Workspace
		// Scheduling the regular mutation persists preparation before its SQL changes.
		err := workflow.ExecuteActivity(ctx, a.ApplyMutation, prepared).Get(ctx, &value)
		return value, err
	}); err != nil {
		return err
	}
	if err := workflow.Await(ctx, func() bool { return completed >= 100 && workflow.AllHandlersFinished(ctx) }); err != nil {
		return err
	}
	return workflow.NewContinueAsNewError(ctx, WorkspacePermissions, id)
}

func Mutate(ctx context.Context, tc client.Client, in Mutation) (workspace.Workspace, error) {
	in.Key = uuid.Must(uuid.NewV7())
	operation := tc.NewWithStartWorkflowOperation(client.StartWorkflowOptions{ID: "workspace-permissions/" + in.WorkspaceID.String(), TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE}, WorkspacePermissions, in.WorkspaceID)
	handle, err := tc.UpdateWithStartWorkflow(ctx, client.UpdateWithStartWorkflowOptions{StartWorkflowOperation: operation, UpdateOptions: client.UpdateWorkflowOptions{UpdateID: in.Key.String(), UpdateName: "mutate", Args: []any{in}, WaitForStage: client.WorkflowUpdateStageAccepted}})
	if err != nil {
		return workspace.Workspace{}, err
	}
	var value workspace.Workspace
	err = handle.Get(ctx, &value)
	return value, err
}
