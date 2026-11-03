package workspace

import (
	"context"
	"errors"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

var workspaceRoles = []string{"owner", "editor", "viewer"}

func graphUpdate(operation v1.RelationshipUpdate_Operation, resourceType, resource, relation, subjectType, subject string) *v1.RelationshipUpdate {
	return &v1.RelationshipUpdate{Operation: operation, Relationship: &v1.Relationship{
		Resource: &v1.ObjectReference{ObjectType: resourceType, ObjectId: resource}, Relation: relation,
		Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: subjectType, ObjectId: subject}},
	}}
}

// InitializeRelationships grants status access before storage is provisioned.
func (s *Store) InitializeRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID) error {
	if id == uuid.Nil {
		return Fault{"VALIDATION"}
	}
	var owner uuid.UUID
	err := s.DB.QueryRow(ctx, `SELECT user_id FROM workspace_members WHERE workspace_id=$1 AND role='owner'`, id).Scan(&owner)
	if errors.Is(err, pgx.ErrNoRows) {
		return Fault{"NOT_FOUND"}
	}
	if err != nil {
		return err
	}
	var updates []*v1.RelationshipUpdate
	for _, role := range workspaceRoles {
		group := id.String() + "/" + role
		updates = append(updates, graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "role_grant", group, "role", "role", role), graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "workspace", id.String(), "grant", "role_grant", group))
	}
	updates = append(updates, graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "role_grant", id.String()+"/owner", "member", "user", owner.String()))
	_, err = graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: updates})
	return err
}

// WriteMemberRelationships changes only the affected members in one atomic graph write.
func (s *Store) WriteMemberRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID, users ...uuid.UUID) error {
	if id == uuid.Nil || len(users) == 0 || len(users) > 100 {
		return Fault{"VALIDATION"}
	}
	rows, err := s.DB.Query(ctx, `SELECT user_id,role FROM workspace_members WHERE workspace_id=$1 AND user_id=ANY($2)`, id, users)
	if err != nil {
		return err
	}
	members, err := pgx.CollectRows(rows, pgx.RowToStructByPos[Member])
	if err != nil {
		return err
	}
	roles := make(map[uuid.UUID]string, len(members))
	for _, member := range members {
		roles[member.UserID] = member.Role
	}
	var updates []*v1.RelationshipUpdate
	seen := make(map[uuid.UUID]bool, len(users))
	for _, user := range users {
		if user == uuid.Nil || seen[user] {
			return Fault{"VALIDATION"}
		}
		seen[user] = true
		for _, role := range workspaceRoles {
			op := v1.RelationshipUpdate_OPERATION_DELETE
			if roles[user] == role {
				op = v1.RelationshipUpdate_OPERATION_TOUCH
			}
			updates = append(updates, graphUpdate(op, "role_grant", id.String()+"/"+role, "member", "user", user.String()))
		}
	}
	_, err = graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: updates})
	return err
}

func (s *Store) PublishStorageRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID) error {
	var lifecycle string
	var bucket, fs *uuid.UUID
	if err := s.DB.QueryRow(ctx, `SELECT status,quota_bucket_id,filesystem_id FROM workspaces WHERE id=$1`, id).Scan(&lifecycle, &bucket, &fs); err != nil {
		return err
	}
	return writeStorageRelationships(ctx, graph, id, bucket, fs, lifecycle == "active")
}

// PublishActivationRelationships runs before SQL activation, while membership and deletion are still blocked.
func (s *Store) PublishActivationRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID) error {
	var lifecycle string
	var bucket, fs *uuid.UUID
	if err := s.DB.QueryRow(ctx, `SELECT status,quota_bucket_id,filesystem_id FROM workspaces WHERE id=$1`, id).Scan(&lifecycle, &bucket, &fs); err != nil {
		return err
	}
	// An active retry must not re-enable storage after a concurrent deletion.
	if lifecycle == "active" {
		return nil
	}
	if lifecycle != "provisioning" || bucket == nil || fs == nil {
		return Fault{"STATE_CONFLICT"}
	}
	return writeStorageRelationships(ctx, graph, id, bucket, fs, true)
}
func writeStorageRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID, bucket, fs *uuid.UUID, enabled bool) error {
	op := v1.RelationshipUpdate_OPERATION_DELETE
	if enabled {
		op = v1.RelationshipUpdate_OPERATION_TOUCH
	}
	updates := []*v1.RelationshipUpdate{graphUpdate(op, "workspace", id.String(), "enabled", "user", "*")}
	if bucket != nil {
		updates = append(updates, graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "quota_bucket", bucket.String(), "workspace", "workspace", id.String()))
	}
	if fs != nil {
		updates = append(updates, graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "filesystem", fs.String(), "workspace", "workspace", id.String()))
	}
	_, err := graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: updates})
	return err
}

func (s *Store) DeleteMemberRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID) error {
	for _, role := range []string{"editor", "viewer"} {
		if _, err := graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "role_grant", OptionalResourceId: id.String() + "/" + role, OptionalRelation: "member"}}); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) RelationshipIDs(ctx context.Context, after uuid.UUID) ([]uuid.UUID, error) {
	rows, err := s.DB.Query(ctx, `SELECT id FROM workspaces WHERE id>$1 ORDER BY id LIMIT 100`, after)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
}

// RebuildWorkspaceRelationships is offline recovery only; normal mutations never enumerate members.
func (s *Store) RebuildWorkspaceRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID) error {
	if err := s.InitializeRelationships(ctx, graph, id); err != nil {
		return err
	}
	for _, role := range workspaceRoles {
		if _, err := graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "role_grant", OptionalResourceId: id.String() + "/" + role, OptionalRelation: "member"}}); err != nil {
			return err
		}
	}
	after := uuid.Nil
	for {
		members, err := s.Members(ctx, id, after, 100)
		if err != nil {
			return err
		}
		if len(members) == 0 {
			break
		}
		ids := make([]uuid.UUID, len(members))
		for i, member := range members {
			ids[i] = member.UserID
		}
		if err = s.WriteMemberRelationships(ctx, graph, id, ids...); err != nil {
			return err
		}
		after = ids[len(ids)-1]
		if len(ids) < 100 {
			break
		}
	}
	return s.PublishStorageRelationships(ctx, graph, id)
}

func (s *Store) RebuildRelationships(ctx context.Context, graph v1.PermissionsServiceClient) error {
	after := uuid.Nil
	for {
		ids, err := s.RelationshipIDs(ctx, after)
		if err != nil {
			return err
		}
		for _, id := range ids {
			item, cancel := context.WithTimeout(ctx, 2*time.Minute)
			err = s.RebuildWorkspaceRelationships(item, graph, id)
			cancel()
			if err != nil {
				return err
			}
			after = id
		}
		if len(ids) < 100 {
			return nil
		}
	}
}
