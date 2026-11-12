package platform

import (
	"context"
	"encoding/hex"
	"time"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	fs "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/platform/v1"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
)

type ProvisionInput struct {
	Subject, UserID, WorkspaceID, SharedStorageID, SharedRootID, PrivateStorageID, PrivateRootID, Name, DisplayName string
	AvatarURL                                                                                                       *string
	Request                                                                                                         *pb.CreateWorkspaceRequest
	Quota                                                                                                           int64
}
type ProvisionResult struct {
	User      *pb.User
	Workspace *pb.Workspace
	Existing  bool
	ZedToken  string
}
type MemberStorageInput struct{ WorkspaceID, UserID, StorageID, RootID, ZedToken string }

func RegisterWorker(w worker.Worker, s *Server) {
	w.RegisterWorkflow(ProvisionWorkspace)
	w.RegisterWorkflow(ProvisionMemberStorage)
	w.RegisterWorkflow(DeleteWorkspace)
	w.RegisterWorkflow(Maintenance)
	w.RegisterActivityWithOptions(s.admitWorkspace, activity.RegisterOptions{Name: "AdmitWorkspace"})
	w.RegisterActivityWithOptions(s.provisionWorkspaceResources, activity.RegisterOptions{Name: "ProvisionWorkspaceResources"})
	w.RegisterActivityWithOptions(s.activateWorkspace, activity.RegisterOptions{Name: "ActivateWorkspace"})
	w.RegisterActivityWithOptions(s.provisionMemberStorage, activity.RegisterOptions{Name: "ProvisionMemberStorageResources"})
	w.RegisterActivityWithOptions(s.deleteWorkspaceResources, activity.RegisterOptions{Name: "DeleteWorkspaceResources"})
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
	if err := workflow.ExecuteActivity(ctx, "ProvisionWorkspaceResources", in).Get(ctx, &result.ZedToken); err != nil {
		return nil, err
	}
	if err := workflow.ExecuteActivity(ctx, "ActivateWorkspace", in.WorkspaceID).Get(ctx, &result.Workspace); err != nil {
		return nil, err
	}
	return &result, nil
}
func ProvisionMemberStorage(ctx workflow.Context, in MemberStorageInput) error {
	return workflow.ExecuteActivity(activityContext(ctx), "ProvisionMemberStorageResources", in).Get(ctx, nil)
}
func DeleteWorkspace(ctx workflow.Context, id string) error {
	return workflow.ExecuteActivity(activityContext(ctx), "DeleteWorkspaceResources", id).Get(ctx, nil)
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
		out.User, err = scanUser(tx.QueryRow(ctx, `WITH inserted AS (INSERT INTO users(id,clerk_subject,display_name,avatar_url) VALUES($1,$2,$3,$4) ON CONFLICT(clerk_subject) DO NOTHING RETURNING id,display_name,avatar_url) SELECT id,display_name,avatar_url FROM inserted UNION ALL SELECT id,display_name,avatar_url FROM users WHERE clerk_subject=$2 AND NOT EXISTS(SELECT 1 FROM inserted)`, in.UserID, in.Subject, in.DisplayName, in.AvatarURL))
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
func (s *Server) provisionWorkspaceResources(ctx context.Context, in ProvisionInput) (string, error) {
	if err := s.write(ctx, sdk.Touch(sdk.Relation("workspace", in.WorkspaceID, "owner", "user", in.UserID, ""))); err != nil {
		return "", err
	}
	if _, err := s.LetFS.ProvisionWorkspaceStorage(ctx, &fs.ProvisionWorkspaceStorageRequest{WorkspaceId: in.WorkspaceID, QuotaBytes: in.Quota}); err != nil {
		return "", err
	}
	if _, err := s.LetFS.CreateStorage(ctx, &fs.CreateStorageRequest{WorkspaceId: in.WorkspaceID, StorageId: in.SharedStorageID, RootNodeId: in.SharedRootID, Owner: &fs.StorageOwnership{Owner: &fs.StorageOwnership_WorkspaceId{WorkspaceId: in.WorkspaceID}}, Name: "Shared", Visibility: fs.StorageVisibility_STORAGE_VISIBILITY_PUBLIC, AllowBlobFiles: true, AllowIndexing: true}); err != nil {
		return "", err
	}
	var headers metadata.MD
	_, err := s.LetFS.CreateStorage(ctx, &fs.CreateStorageRequest{WorkspaceId: in.WorkspaceID, StorageId: in.PrivateStorageID, RootNodeId: in.PrivateRootID, Owner: &fs.StorageOwnership{Owner: &fs.StorageOwnership_UserId{UserId: in.UserID}}, Name: "Personal", Visibility: fs.StorageVisibility_STORAGE_VISIBILITY_PRIVATE, AllowBlobFiles: true, AllowIndexing: true}, grpc.Header(&headers))
	if err != nil {
		return "", err
	}
	return headers.Get("x-openlet-zed-token")[0], nil
}
func (s *Server) activateWorkspace(ctx context.Context, id string) (*pb.Workspace, error) {
	return scanWorkspace(s.DB.QueryRow(ctx, `UPDATE workspaces SET state='active' WHERE id=$1 AND state IN ('provisioning','active') RETURNING id,name,state,created_at`, id))
}
func (s *Server) provisionMember(ctx context.Context, workspace, user, request, token string) error {
	_, err := s.Temporal.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "member-storage/" + workspace + "/" + user + "/" + request, TaskQueue: s.Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE}, ProvisionMemberStorage, MemberStorageInput{ZedToken: token, WorkspaceID: workspace, UserID: user, StorageID: uuid.NewString(), RootID: uuid.NewString()})
	return err
}
func (s *Server) provisionMemberStorage(ctx context.Context, in MemberStorageInput) error {
	if in.ZedToken != "" {
		md, _ := metadata.FromIncomingContext(ctx)
		md = md.Copy()
		md.Set("x-openlet-zed-token", in.ZedToken)
		ctx = metadata.NewIncomingContext(ctx, md)
		ctx = metadata.AppendToOutgoingContext(ctx, "x-openlet-zed-token", in.ZedToken)
	}
	check, err := s.Graph.CheckPermission(ctx, &az.CheckPermissionRequest{Resource: sdk.Object("workspace", in.WorkspaceID), Permission: "participate", Subject: sdk.Subject(sdk.Actor{Type: "user", ID: in.UserID}), Consistency: sdk.Consistency(ctx)})
	if err != nil {
		return err
	}
	if check.Permissionship != az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION {
		return nil
	}
	request := &fs.ListStoragesRequest{WorkspaceId: in.WorkspaceID, OwnedOnly: true, PageSize: 100}
	for {
		rows, err := s.Storages.ListStorages(sdk.WithActor(ctx, sdk.Actor{Type: "user", ID: in.UserID}), request)
		if err != nil {
			return err
		}
		if len(rows.Storages) > 0 {
			return nil
		}
		if rows.NextPageToken == "" {
			break
		}
		request.PageToken = rows.NextPageToken
	}
	_, err = s.LetFS.CreateStorage(ctx, &fs.CreateStorageRequest{WorkspaceId: in.WorkspaceID, StorageId: in.StorageID, RootNodeId: in.RootID, Owner: &fs.StorageOwnership{Owner: &fs.StorageOwnership_UserId{UserId: in.UserID}}, Name: "Personal", Visibility: fs.StorageVisibility_STORAGE_VISIBILITY_PRIVATE, AllowBlobFiles: true, AllowIndexing: true})
	return err
}
func (s *Server) deleteWorkspaceResources(ctx context.Context, id string) error {
	// Revocation precedes storage cleanup; no Leta runtime barrier.
	if _, err := s.Graph.DeleteRelationships(ctx, &az.DeleteRelationshipsRequest{RelationshipFilter: &az.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: id}}); err != nil {
		return err
	}
	if _, err := s.LetFS.DeleteWorkspaceStorage(ctx, &fs.WorkspaceStorageRequest{WorkspaceId: id}); err != nil {
		return err
	}
	_, err := s.DB.Exec(ctx, `DELETE FROM workspaces WHERE id=$1 AND state='deleting'`, id)
	return err
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
		if _, err = s.Temporal.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "delete-workspace/" + id, TaskQueue: s.Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE}, DeleteWorkspace, id); err != nil {
			return err
		}
	}
	return nil
}
func hexHash(b []byte) string { return hex.EncodeToString(b) }
