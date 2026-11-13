package storage

import (
	"context"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
)

func scanStorage(row pgx.Row) (*pb.Storage, error) {
	v := new(pb.Storage)
	var visibility string
	err := row.Scan(&v.Id, &v.WorkspaceId, &v.Name, &visibility, &v.RootNodeId, &v.AllowBlobFiles, &v.AllowIndexing)
	v.Visibility = visibilityValue(visibility)
	return v, err
}
func visibilityValue(s string) pb.StorageVisibility {
	if s == "public" {
		return pb.StorageVisibility_STORAGE_VISIBILITY_PUBLIC
	}
	return pb.StorageVisibility_STORAGE_VISIBILITY_PRIVATE
}
func visibilityName(v pb.StorageVisibility) string {
	if v == pb.StorageVisibility_STORAGE_VISIBILITY_PUBLIC {
		return "public"
	}
	return "private"
}

const storageColumns = `id,workspace_id,name,visibility,root_node_id,allow_blob_files,allow_indexing`

func (s *Server) ProvisionWorkspaceStorage(ctx context.Context, r *pb.ProvisionWorkspaceStorageRequest) (*pb.WorkspaceStorage, error) {
	v := new(pb.WorkspaceStorage)
	err := s.DB.QueryRow(ctx, `INSERT INTO workspace_storage(workspace_id,quota_bytes) VALUES($1,$2) ON CONFLICT(workspace_id) DO UPDATE SET workspace_id=excluded.workspace_id RETURNING workspace_id,quota_bytes,used_bytes`, r.WorkspaceId, r.QuotaBytes).Scan(&v.WorkspaceId, &v.QuotaBytes, &v.UsedBytes)
	return v, err
}
func (s *Server) CreateStorage(ctx context.Context, r *pb.CreateStorageRequest) (*pb.Storage, error) {
	if r.Owner == nil || r.Owner.Owner == nil {
		return nil, invalid("storage owner is required")
	}
	if o, ok := r.Owner.Owner.(*pb.StorageOwnership_WorkspaceId); ok && o.WorkspaceId != r.WorkspaceId {
		return nil, invalid("owner workspace must be the storage workspace")
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	tag, err := tx.Exec(ctx, `INSERT INTO storages(id,workspace_id,name,visibility,root_node_id,allow_blob_files,allow_indexing) VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(id) DO NOTHING`, r.StorageId, r.WorkspaceId, r.Name, visibilityName(r.Visibility), r.RootNodeId, r.AllowBlobFiles, r.AllowIndexing)
	if err != nil {
		return nil, err
	}
	if tag.RowsAffected() > 0 {
		if _, err = tx.Exec(ctx, `INSERT INTO nodes(id,storage_id,name,kind) VALUES($1,$2,'','directory')`, r.RootNodeId, r.StorageId); err != nil {
			return nil, err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	updates := []*az.RelationshipUpdate{sdk.Touch(sdk.Relation("storage", r.StorageId, "workspace", "workspace", r.WorkspaceId, ""))}
	switch o := r.Owner.Owner.(type) {
	case *pb.StorageOwnership_UserId:
		updates = append(updates, sdk.Touch(sdk.Relation("storage", r.StorageId, "owner", "user", o.UserId, "")))
	case *pb.StorageOwnership_AgentId:
		updates = append(updates, sdk.Touch(sdk.Relation("storage", r.StorageId, "owner", "agent", o.AgentId, "")), sdk.Touch(sdk.Relation("storage", r.StorageId, "owner", "agent", o.AgentId, "owner")))
	case *pb.StorageOwnership_WorkspaceId:
		updates = append(updates, sdk.Touch(sdk.Relation("storage", r.StorageId, "owner", "workspace", r.WorkspaceId, "owner")))
	}
	if r.Visibility == pb.StorageVisibility_STORAGE_VISIBILITY_PUBLIC {
		updates = append(updates, sdk.Touch(sdk.Relation("storage", r.StorageId, "public_workspace", "workspace", r.WorkspaceId, "")))
	}
	written, err := s.Graph.WriteRelationships(ctx, &az.WriteRelationshipsRequest{Updates: updates})
	if err != nil {
		return nil, err
	}
	if err = grpc.SetHeader(ctx, metadata.Pairs("x-openlet-zed-token", written.WrittenAt.Token)); err != nil {
		return nil, err
	}
	return &pb.Storage{Id: r.StorageId, WorkspaceId: r.WorkspaceId, Name: r.Name, Visibility: r.Visibility, RootNodeId: r.RootNodeId, AllowBlobFiles: r.AllowBlobFiles, AllowIndexing: r.AllowIndexing}, nil
}
func (s *Server) DeleteStorage(ctx context.Context, r *pb.StorageRequest) (*emptypb.Empty, error) {
	// Match the SQL tenant before touching the canonical graph.
	var id string
	err := s.DB.QueryRow(ctx, `SELECT id FROM storages WHERE id=$1 AND workspace_id=$2`, r.StorageId, r.WorkspaceId).Scan(&id)
	if err == pgx.ErrNoRows {
		return &emptypb.Empty{}, nil
	}
	if err != nil {
		return nil, err
	}
	if _, err = s.Graph.DeleteRelationships(ctx, &az.DeleteRelationshipsRequest{RelationshipFilter: &az.RelationshipFilter{ResourceType: "storage", OptionalResourceId: id}}); err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	var bytes int64
	err = tx.QueryRow(ctx, `WITH doomed AS (DELETE FROM nodes n USING files f WHERE n.storage_id=$1 AND f.node_id=n.id RETURNING f.size_bytes), cleared AS (DELETE FROM nodes WHERE storage_id=$1 AND kind='directory') SELECT coalesce(sum(size_bytes),0) FROM doomed`, id).Scan(&bytes)
	if err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM storages WHERE id=$1`, id); err != nil {
		return nil, err
	}
	if err = s.quota(ctx, tx, r.WorkspaceId, -bytes); err != nil {
		return nil, err
	}
	return &emptypb.Empty{}, tx.Commit(ctx)
}
func (s *Server) GetWorkspaceStorage(ctx context.Context, r *pb.WorkspaceStorageRequest) (*pb.WorkspaceStorage, error) {
	if _, err := s.check(ctx, "workspace", r.WorkspaceId, "view"); err != nil {
		return nil, err
	}
	v := new(pb.WorkspaceStorage)
	err := s.DB.QueryRow(ctx, `SELECT workspace_id,quota_bytes,used_bytes FROM workspace_storage WHERE workspace_id=$1`, r.WorkspaceId).Scan(&v.WorkspaceId, &v.QuotaBytes, &v.UsedBytes)
	return v, err
}
func (s *Server) UpdateStorageQuota(ctx context.Context, r *pb.UpdateStorageQuotaRequest) (*pb.WorkspaceStorage, error) {
	if _, err := s.check(ctx, "workspace", r.WorkspaceId, "manage"); err != nil {
		return nil, err
	}
	v := new(pb.WorkspaceStorage)
	err := s.DB.QueryRow(ctx, `UPDATE workspace_storage SET quota_bytes=$2 WHERE workspace_id=$1 AND used_bytes<=$2 RETURNING workspace_id,quota_bytes,used_bytes`, r.WorkspaceId, r.QuotaBytes).Scan(&v.WorkspaceId, &v.QuotaBytes, &v.UsedBytes)
	if err == pgx.ErrNoRows {
		return nil, invalid("quota cannot be lower than current usage")
	}
	return v, err
}
func (s *Server) GetStorage(ctx context.Context, r *pb.StorageRequest) (*pb.Storage, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "read")
	if err != nil {
		return nil, err
	}
	v, err := scanStorage(s.DB.QueryRow(ctx, `SELECT `+storageColumns+` FROM storages WHERE id=$1 AND workspace_id=$2`, r.StorageId, r.WorkspaceId))
	if err != nil {
		return nil, err
	}
	if err = s.capabilities(ctx, a, []*pb.Storage{v}); err != nil {
		return nil, err
	}
	return v, nil
}
func (s *Server) capabilities(ctx context.Context, a sdk.Actor, storages []*pb.Storage) error {
	if len(storages) == 0 {
		return nil
	}
	items := make([]*az.CheckBulkPermissionsRequestItem, 0, len(storages)*3)
	for _, v := range storages {
		for _, permission := range []string{"read", "write", "manage_access"} {
			items = append(items, &az.CheckBulkPermissionsRequestItem{Resource: sdk.Object("storage", v.Id), Permission: permission, Subject: sdk.Subject(a)})
		}
	}
	checks, err := s.Graph.CheckBulkPermissions(ctx, &az.CheckBulkPermissionsRequest{Items: items, Consistency: sdk.Consistency(ctx)})
	if err != nil {
		return err
	}
	byID := map[string]*pb.Storage{}
	for _, v := range storages {
		v.Capabilities = new(pb.StorageCapabilities)
		byID[v.Id] = v
	}
	for _, p := range checks.Pairs {
		if e := p.GetError(); e != nil {
			return status.FromProto(e).Err()
		}
		v := byID[p.Request.Resource.ObjectId]
		allowed := p.GetItem().Permissionship == az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION
		switch p.Request.Permission {
		case "read":
			v.Capabilities.Read = allowed
		case "write":
			v.Capabilities.Write = allowed
		case "manage_access":
			v.Capabilities.ManageAccess = allowed
		}
	}
	return nil
}
func (s *Server) ListStorages(ctx context.Context, r *pb.ListStoragesRequest) (*pb.ListStoragesResponse, error) {
	a, err := s.check(ctx, "workspace", r.WorkspaceId, "view")
	if err != nil {
		// Registered agents may discover storages without human-only workspace.view.
		if actor, e := sdk.ActorFromContext(ctx); e == nil && actor.Type == "agent" {
			a, err = s.check(ctx, "workspace", r.WorkspaceId, "eligible_actor")
		}
		if err != nil {
			return nil, err
		}
	}
	if r.PageToken != "" {
		if _, err = uuid.Parse(r.PageToken); err != nil {
			return nil, invalid("invalid storage cursor")
		}
	}
	var visibility any
	if r.Visibility != nil {
		visibility = visibilityName(*r.Visibility)
	}
	rows, err := s.DB.Query(ctx, `SELECT `+storageColumns+` FROM storages WHERE workspace_id=$1 AND ($2::text IS NULL OR visibility=$2) AND ($3::uuid IS NULL OR id>$3) ORDER BY id LIMIT $4`, r.WorkspaceId, visibility, nilString(r.PageToken), pageSize(r.PageSize)+1)
	if err != nil {
		return nil, err
	}
	candidates := []*pb.Storage{}
	for rows.Next() {
		v, err := scanStorage(rows)
		if err != nil {
			rows.Close()
			return nil, err
		}
		candidates = append(candidates, v)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return nil, err
	}
	out := new(pb.ListStoragesResponse)
	if len(candidates) > pageSize(r.PageSize) {
		candidates = candidates[:pageSize(r.PageSize)]
		out.NextPageToken = candidates[len(candidates)-1].Id
	}
	if err = s.capabilities(ctx, a, candidates); err != nil {
		return nil, err
	}
	for _, v := range candidates {
		if v.Capabilities.Read && (!r.OwnedOnly || v.Capabilities.ManageAccess) {
			out.Storages = append(out.Storages, v)
		}
	}
	return out, nil
}
