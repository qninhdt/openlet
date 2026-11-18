package platform

import (
	"context"
	"encoding/hex"
	"time"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/platform/v1"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

type ProvisionInput struct {
	Subject, UserID, WorkspaceID, SharedStorageID, SharedRootID, PrivateStorageID, PrivateRootID, Name, DisplayName string
	AvatarURL                                                                                                       *string
	Request                                                                                                         *pb.CreateWorkspaceRequest
	Quota                                                                                                           int64
	LetFSQueue                                                                                                      string
}
type ProvisionResult struct {
	User      *pb.User
	Workspace *pb.Workspace
	Existing  bool
	ZedToken  string
}
type DeleteWorkspaceInput struct {
	WorkspaceID     string
	LetFSQueue      string
	LetaBridgeQueue string
}

func RegisterWorker(w worker.Worker, s *Server) {
	w.RegisterWorkflow(ProvisionWorkspace)
	w.RegisterWorkflow(ProvisionMemberStorage)
	w.RegisterWorkflow(DeleteWorkspace)
	w.RegisterWorkflow(Maintenance)
	w.RegisterActivityWithOptions(s.admitWorkspace, activity.RegisterOptions{Name: "AdmitWorkspace"})
	w.RegisterActivityWithOptions(s.provisionWorkspaceAccess, activity.RegisterOptions{Name: "ProvisionWorkspaceAccess"})
	w.RegisterActivityWithOptions(s.activateWorkspace, activity.RegisterOptions{Name: "ActivateWorkspace"})
	w.RegisterActivityWithOptions(s.revokeWorkspaceAccess, activity.RegisterOptions{Name: "RevokeWorkspaceAccess"})
	w.RegisterActivityWithOptions(s.deleteWorkspaceRecord, activity.RegisterOptions{Name: "DeleteWorkspaceRecord"})
	w.RegisterActivityWithOptions(s.maintenance, activity.RegisterOptions{Name: "PlatformMaintenance"})
}
func activityContext(ctx workflow.Context) workflow.Context {
	return workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 2 * time.Minute, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: time.Minute, MaximumAttempts: 10}})
}
func ProvisionWorkspace(ctx workflow.Context, in ProvisionInput) (*ProvisionResult, error) {
	ctx = activityContext(ctx)
	var result ProvisionResult
	if err := workflow.ExecuteActivity(ctx, "AdmitWorkspace", in).Get(ctx, &result); err != nil {
		return nil, err
	}
	if result.Existing {
		return &result, nil
	}
	if err := workflow.ExecuteActivity(ctx, "ProvisionWorkspaceAccess", in).Get(ctx, &result.ZedToken); err != nil {
		return nil, err
	}
	storageCtx := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{TaskQueue: in.LetFSQueue, StartToCloseTimeout: 2 * time.Minute, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 10}})
	if err := workflow.ExecuteActivity(storageCtx, "ProvisionInitialStorages", sdk.InitialStoragesInput{WorkspaceID: in.WorkspaceID, UserID: in.UserID, SharedStorageID: in.SharedStorageID, SharedRootID: in.SharedRootID, PrivateStorageID: in.PrivateStorageID, PrivateRootID: in.PrivateRootID, Quota: in.Quota, ZedToken: result.ZedToken}).Get(ctx, &result.ZedToken); err != nil {
		return nil, err
	}
	if err := workflow.ExecuteActivity(ctx, "ActivateWorkspace", in.WorkspaceID).Get(ctx, &result.Workspace); err != nil {
		return nil, err
	}
	return &result, nil
}
func ProvisionMemberStorage(ctx workflow.Context, in sdk.MemberStorageInput) error {
	ctx = workflow.WithActivityOptions(activityContext(ctx), workflow.ActivityOptions{TaskQueue: in.LetFSQueue, StartToCloseTimeout: 2 * time.Minute, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 10}})
	return workflow.ExecuteActivity(ctx, "ProvisionMemberStorageResources", in).Get(ctx, nil)
}
func DeleteWorkspace(ctx workflow.Context, in DeleteWorkspaceInput) error {
	if _, err := uuid.Parse(in.WorkspaceID); err != nil || in.LetFSQueue == "" || in.LetaBridgeQueue == "" {
		return temporal.NewNonRetryableApplicationError("workspace ID and owning cleanup queues are required", "invalid_cleanup_input", nil)
	}
	options := workflow.ActivityOptions{StartToCloseTimeout: 2 * time.Minute, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: time.Minute}}
	local := workflow.WithActivityOptions(ctx, options)
	payload := sdk.WorkspaceCleanup{WorkspaceID: in.WorkspaceID}
	if err := workflow.ExecuteActivity(local, "RevokeWorkspaceAccess", payload).Get(ctx, nil); err != nil {
		return err
	}
	options.TaskQueue = in.LetFSQueue
	storage := workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, options), "DeleteWorkspaceStorage", payload)
	options.TaskQueue = in.LetaBridgeQueue
	options.StartToCloseTimeout = 24 * time.Hour
	options.HeartbeatTimeout = 30 * time.Second
	agents := workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, options), "DeleteWorkspaceAgents", payload)
	storageErr := storage.Get(ctx, nil)
	var recordErr error
	if storageErr == nil {
		recordErr = workflow.ExecuteActivity(local, "DeleteWorkspaceRecord", payload).Get(ctx, nil)
	}
	agentsErr := agents.Get(ctx, nil)
	if storageErr != nil {
		return storageErr
	}
	if recordErr != nil {
		return recordErr
	}
	return agentsErr
}
func Maintenance(ctx workflow.Context) error {
	return workflow.ExecuteActivity(activityContext(ctx), "PlatformMaintenance").Get(ctx, nil)
}
func (s *Server) admitWorkspace(ctx context.Context, in ProvisionInput) (*ProvisionResult, error) {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(ProvisionResult)
	if in.Subject != "" {
		out.User, err = scanUser(tx.QueryRow(ctx, `WITH inserted AS (INSERT INTO users(id,clerk_subject,display_name,avatar_url) VALUES($1,$2,$3,$4) ON CONFLICT(clerk_subject) DO NOTHING RETURNING id,display_name,avatar_url,appearance) SELECT id,display_name,avatar_url,appearance FROM inserted UNION ALL SELECT id,display_name,avatar_url,appearance FROM users WHERE clerk_subject=$2 AND NOT EXISTS(SELECT 1 FROM inserted)`, in.UserID, in.Subject, in.DisplayName, in.AvatarURL))
		if err != nil {
			return nil, err
		}
		if out.User.Id != in.UserID {
			out.Existing = true
			return out, tx.Commit(ctx)
		}
	} else {
		out.Workspace = new(pb.Workspace)
		duplicate, err := sdk.Claim(ctx, tx, "system", "CreateWorkspace", in.Request.RequestId, in.Request, out.Workspace, s.receiptTTL())
		if err != nil {
			return nil, err
		}
		if duplicate && out.Workspace.Id != in.WorkspaceID {
			out.Existing = true
			return out, tx.Commit(ctx)
		}
	}
	out.Workspace, err = scanWorkspace(tx.QueryRow(ctx, `INSERT INTO workspaces(id,name,state) VALUES($1,$2,'provisioning') ON CONFLICT(id) DO UPDATE SET name=workspaces.name RETURNING id,name,state,created_at`, in.WorkspaceID, in.Name))
	if err != nil {
		return nil, err
	}
	if in.Request != nil {
		if err = sdk.Finish(ctx, tx, "system", "CreateWorkspace", in.Request.RequestId, out.Workspace); err != nil {
			return nil, err
		}
	}
	return out, tx.Commit(ctx)
}
func (s *Server) provisionWorkspaceAccess(ctx context.Context, in ProvisionInput) (string, error) {
	result, err := s.Graph.WriteRelationships(ctx, &az.WriteRelationshipsRequest{Updates: []*az.RelationshipUpdate{sdk.Touch(sdk.Relation("workspace", in.WorkspaceID, "owner", "user", in.UserID, ""))}})
	if err != nil {
		return "", err
	}
	return result.WrittenAt.Token, nil
}
func (s *Server) activateWorkspace(ctx context.Context, id string) (*pb.Workspace, error) {
	return scanWorkspace(s.DB.QueryRow(ctx, `UPDATE workspaces SET state='active' WHERE id=$1 AND state IN ('provisioning','active') RETURNING id,name,state,created_at`, id))
}
func (s *Server) provisionMember(ctx context.Context, workspace, user, request, token string) error {
	_, err := s.Temporal.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "member-storage/" + workspace + "/" + user + "/" + request, TaskQueue: s.Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE}, ProvisionMemberStorage, sdk.MemberStorageInput{LetFSQueue: s.Queues.LetFS, ZedToken: token, WorkspaceID: workspace, UserID: user, StorageID: uuid.NewString(), RootID: uuid.NewString()})
	return err
}
func (s *Server) revokeWorkspaceAccess(ctx context.Context, in sdk.WorkspaceCleanup) error {
	_, err := s.Graph.DeleteRelationships(ctx, &az.DeleteRelationshipsRequest{RelationshipFilter: &az.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: in.WorkspaceID}})
	return err
}
func (s *Server) deleteWorkspaceRecord(ctx context.Context, in sdk.WorkspaceCleanup) error {
	_, err := s.DB.Exec(ctx, `DELETE FROM workspaces WHERE id=$1 AND state='deleting'`, in.WorkspaceID)
	return err
}
func (s *Server) cleanupInput(id string) DeleteWorkspaceInput {
	return DeleteWorkspaceInput{WorkspaceID: id, LetFSQueue: s.Queues.LetFS, LetaBridgeQueue: s.Queues.LetaBridge}
}
func (s *Server) maintenance(ctx context.Context) error {
	if _, err := s.DB.Exec(ctx, `DELETE FROM idempotency_keys WHERE (caller,method,key) IN (SELECT caller,method,key FROM idempotency_keys WHERE expires_at<now() LIMIT 500)`); err != nil {
		return err
	}
	if _, err := s.DB.Exec(ctx, `DELETE FROM invitations WHERE id IN (SELECT id FROM invitations WHERE expires_at<now() AND accepted_by IS NULL LIMIT 500)`); err != nil {
		return err
	}
	rows, err := s.DB.Query(ctx, `SELECT id FROM workspaces WHERE state='deleting' ORDER BY id LIMIT 100`)
	if err != nil {
		return err
	}
	ids := []string{}
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		ids = append(ids, id)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return err
	}
	for _, id := range ids {
		if _, err = s.Temporal.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "delete-workspace/" + id, TaskQueue: s.Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE}, DeleteWorkspace, s.cleanupInput(id)); err != nil {
			return err
		}
	}
	return nil
}
func hexHash(b []byte) string { return hex.EncodeToString(b) }
