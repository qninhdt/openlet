package platform

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"time"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/platform/v1"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"google.golang.org/grpc"
	grpcmetadata "google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/proto"
)

func (s *Server) ListWorkspaces(ctx context.Context, r *pb.ListWorkspacesRequest) (*pb.ListWorkspacesResponse, error) {
	a, err := human(ctx)
	if err != nil {
		return nil, err
	}
	req := &az.LookupResourcesRequest{ResourceObjectType: "workspace", Permission: "view", Subject: sdk.Subject(a), Consistency: sdk.Consistency(ctx), OptionalLimit: pageSize(r.PageSize)}
	if r.PageToken != "" {
		req.OptionalCursor = &az.Cursor{Token: r.PageToken}
	}
	stream, err := s.Graph.LookupResources(ctx, req)
	if err != nil {
		return nil, err
	}
	ids := []string{}
	var next string
	for {
		v, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		ids = append(ids, v.ResourceObjectId)
		next = v.AfterResultCursor.Token
	}
	out := new(pb.ListWorkspacesResponse)
	if len(ids) == 0 {
		return out, nil
	}
	if len(ids) == int(req.OptionalLimit) {
		out.NextPageToken = next
	}
	items := make([]*az.CheckBulkPermissionsRequestItem, 0, len(ids))
	for _, id := range ids {
		items = append(items, &az.CheckBulkPermissionsRequestItem{Resource: sdk.Object("workspace", id), Permission: "manage", Subject: sdk.Subject(a)})
	}
	checks, err := s.Graph.CheckBulkPermissions(ctx, &az.CheckBulkPermissionsRequest{Items: items, Consistency: sdk.Consistency(ctx)})
	if err != nil {
		return nil, err
	}
	roles := map[string]pb.WorkspaceRole{}
	for _, p := range checks.Pairs {
		if p.GetError() != nil {
			return nil, statusFromProto(p.GetError())
		}
		role := pb.WorkspaceRole_WORKSPACE_ROLE_MEMBER
		if p.GetItem().Permissionship == az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION {
			role = pb.WorkspaceRole_WORKSPACE_ROLE_OWNER
		}
		roles[p.Request.Resource.ObjectId] = role
	}
	rows, err := s.DB.Query(ctx, `SELECT w.id,w.name,w.state,w.created_at FROM unnest($1::uuid[]) WITH ORDINALITY x(id,ord) JOIN workspaces w ON w.id=x.id ORDER BY x.ord`, ids)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		w, err := scanWorkspace(rows)
		if err != nil {
			return nil, err
		}
		v := roles[w.Id]
		w.Role = &v
		out.Workspaces = append(out.Workspaces, w)
	}
	return out, rows.Err()
}
func (s *Server) GetWorkspace(ctx context.Context, r *pb.WorkspaceRequest) (*pb.Workspace, error) {
	if _, err := s.check(ctx, r.WorkspaceId, "view"); err != nil {
		return nil, err
	}
	return scanWorkspace(s.DB.QueryRow(ctx, `SELECT id,name,state,created_at FROM workspaces WHERE id=$1`, r.WorkspaceId))
}
func (s *Server) GetWorkspaceInfo(ctx context.Context, r *pb.WorkspaceRequest) (*pb.Workspace, error) {
	return scanWorkspace(s.DB.QueryRow(ctx, `SELECT id,name,state,created_at FROM workspaces WHERE id=$1`, r.WorkspaceId))
}
func (s *Server) UpdateWorkspace(ctx context.Context, r *pb.UpdateWorkspaceRequest) (*pb.Workspace, error) {
	if _, err := s.check(ctx, r.WorkspaceId, "manage"); err != nil {
		return nil, err
	}
	return scanWorkspace(s.DB.QueryRow(ctx, `UPDATE workspaces SET name=coalesce($2,name) WHERE id=$1 AND state='active' RETURNING id,name,state,created_at`, r.WorkspaceId, r.Name))
}
func (s *Server) DeleteWorkspace(ctx context.Context, r *pb.WorkspaceRequest) (*pb.Workspace, error) {
	if _, err := s.check(ctx, r.WorkspaceId, "manage"); err != nil {
		return nil, err
	}
	w, err := scanWorkspace(s.DB.QueryRow(ctx, `UPDATE workspaces SET state='deleting' WHERE id=$1 RETURNING id,name,state,created_at`, r.WorkspaceId))
	if err != nil {
		return nil, err
	}
	_, err = s.Temporal.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "delete-workspace/" + r.WorkspaceId, TaskQueue: s.Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE}, DeleteWorkspace, s.cleanupInput(r.WorkspaceId))
	return w, err
}
func (s *Server) CreateMyWorkspace(ctx context.Context, r *pb.CreateMyWorkspaceRequest) (*pb.Workspace, error) {
	a, err := human(ctx)
	if err != nil {
		return nil, err
	}
	return s.CreateWorkspace(ctx, &pb.CreateWorkspaceRequest{OwnerUserId: a.ID, Name: r.Name, RequestId: r.RequestId})
}
func (s *Server) CreateWorkspace(ctx context.Context, r *pb.CreateWorkspaceRequest) (*pb.Workspace, error) {
	var exists bool
	if err := s.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM users WHERE id=$1)`, r.OwnerUserId).Scan(&exists); err != nil {
		return nil, err
	}
	if !exists {
		return nil, notFound("owner user")
	}
	raw, err := proto.MarshalOptions{Deterministic: true}.Marshal(r)
	if err != nil {
		return nil, err
	}
	hash := sha256.Sum256(raw)
	input := ProvisionInput{LetFSQueue: s.Queues.LetFS, UserID: r.OwnerUserId, WorkspaceID: uuid.NewString(), SharedStorageID: uuid.NewString(), SharedRootID: uuid.NewString(), PrivateStorageID: uuid.NewString(), PrivateRootID: uuid.NewString(), Name: r.Name, Request: r, Quota: s.Settings.DefaultQuotaBytes}
	run, err := s.Temporal.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "create-workspace/" + r.RequestId + "/" + hex.EncodeToString(hash[:]), TaskQueue: s.Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE}, ProvisionWorkspace, input)
	if err != nil {
		return nil, err
	}
	var result ProvisionResult
	if err = run.Get(ctx, &result); err != nil {
		return nil, err
	}
	if result.ZedToken != "" {
		if err = grpc.SetHeader(ctx, grpcmetadata.Pairs("x-openlet-zed-token", result.ZedToken)); err != nil {
			return nil, err
		}
	}
	return result.Workspace, nil
}
func (s *Server) receiptTTL() time.Duration {
	return time.Duration(s.Settings.IdempotencyRetentionSeconds) * time.Second
}
