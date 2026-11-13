package storage

import (
	"context"
	"io"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/protobuf/types/known/emptypb"
)

func actorFromRef(a *pb.ActorRef) sdk.Actor {
	if a.GetAgentId() != "" {
		return sdk.Actor{Type: "agent", ID: a.GetAgentId()}
	}
	return sdk.Actor{Type: "user", ID: a.GetUserId()}
}
func (s *Server) storageParent(ctx context.Context, workspace, storage string) error {
	var id string
	return s.DB.QueryRow(ctx, `SELECT id FROM storages WHERE id=$1 AND workspace_id=$2`, storage, workspace).Scan(&id)
}
func (s *Server) ListStorageAccess(ctx context.Context, r *pb.StorageRequest) (*pb.StorageAccess, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "manage_access"); err != nil {
		return nil, err
	}
	var visibility string
	if err := s.DB.QueryRow(ctx, `SELECT visibility FROM storages WHERE id=$1 AND workspace_id=$2`, r.StorageId, r.WorkspaceId).Scan(&visibility); err != nil {
		return nil, err
	}
	stream, err := s.Graph.ReadRelationships(ctx, &az.ReadRelationshipsRequest{RelationshipFilter: &az.RelationshipFilter{ResourceType: "storage", OptionalResourceId: r.StorageId}, Consistency: sdk.Consistency(ctx)})
	if err != nil {
		return nil, err
	}
	out := &pb.StorageAccess{Visibility: visibilityValue(visibility)}
	for {
		v, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		rel := v.Relationship
		subject := rel.Subject.Object
		switch rel.Relation {
		case "owner":
			if out.Ownership != nil {
				continue
			}
			out.Ownership = new(pb.StorageOwnership)
			switch subject.ObjectType {
			case "user":
				out.Ownership.Owner = &pb.StorageOwnership_UserId{UserId: subject.ObjectId}
			case "agent":
				out.Ownership.Owner = &pb.StorageOwnership_AgentId{AgentId: subject.ObjectId}
			case "workspace":
				out.Ownership.Owner = &pb.StorageOwnership_WorkspaceId{WorkspaceId: subject.ObjectId}
			}
		case "editor", "viewer":
			role := pb.StorageRole_STORAGE_ROLE_VIEWER
			if rel.Relation == "editor" {
				role = pb.StorageRole_STORAGE_ROLE_EDITOR
			}
			out.Grants = append(out.Grants, &pb.AccessGrant{Actor: actorRef(sdk.Actor{Type: subject.ObjectType, ID: subject.ObjectId}), Role: role})
		}
	}
	return out, nil
}
func (s *Server) SetStorageAccess(ctx context.Context, r *pb.SetStorageAccessRequest) (*pb.AccessGrant, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "manage_access"); err != nil {
		return nil, err
	}
	if err := s.storageParent(ctx, r.WorkspaceId, r.StorageId); err != nil {
		return nil, err
	}
	target := actorFromRef(r.Actor)
	check, err := s.Graph.CheckPermission(ctx, &az.CheckPermissionRequest{Resource: sdk.Object("workspace", r.WorkspaceId), Permission: "eligible_actor", Subject: sdk.Subject(target), Consistency: sdk.Consistency(ctx)})
	if err != nil {
		return nil, err
	}
	if check.Permissionship != az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION {
		return nil, permissionDenied()
	}
	role := "viewer"
	other := "editor"
	if r.Role == pb.StorageRole_STORAGE_ROLE_EDITOR {
		role, other = other, role
	}
	_, err = s.Graph.WriteRelationships(ctx, &az.WriteRelationshipsRequest{Updates: []*az.RelationshipUpdate{sdk.Delete(sdk.Relation("storage", r.StorageId, other, target.Type, target.ID, "")), sdk.Touch(sdk.Relation("storage", r.StorageId, role, target.Type, target.ID, ""))}})
	return &pb.AccessGrant{Actor: r.Actor, Role: r.Role}, err
}
func (s *Server) RevokeStorageAccess(ctx context.Context, r *pb.RevokeStorageAccessRequest) (*emptypb.Empty, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "manage_access"); err != nil {
		return nil, err
	}
	if err := s.storageParent(ctx, r.WorkspaceId, r.StorageId); err != nil {
		return nil, err
	}
	a := actorFromRef(r.Actor)
	_, err := s.Graph.WriteRelationships(ctx, &az.WriteRelationshipsRequest{Updates: []*az.RelationshipUpdate{sdk.Delete(sdk.Relation("storage", r.StorageId, "viewer", a.Type, a.ID, "")), sdk.Delete(sdk.Relation("storage", r.StorageId, "editor", a.Type, a.ID, ""))}})
	return &emptypb.Empty{}, err
}
func (s *Server) UpdateStorage(ctx context.Context, r *pb.UpdateStorageRequest) (*pb.Storage, error) {
	_, err := s.check(ctx, "storage", r.StorageId, "manage_access")
	if err != nil {
		return nil, err
	}
	return scanStorage(s.DB.QueryRow(ctx, `UPDATE storages SET name=$3 WHERE id=$1 AND workspace_id=$2 RETURNING `+storageColumns, r.StorageId, r.WorkspaceId, r.Name))
}
