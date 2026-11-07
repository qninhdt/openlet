package workspace

import (
	"context"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/authz"
	"time"
)

var workspaceRoles = []string{"owner", "admin", "member"}

func graphUpdate(op v1.RelationshipUpdate_Operation, kind, id, relation, subjectKind, subject string) *v1.RelationshipUpdate {
	return &v1.RelationshipUpdate{Operation: op, Relationship: &v1.Relationship{
		Resource: &v1.ObjectReference{ObjectType: kind, ObjectId: id}, Relation: relation,
		Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: subjectKind, ObjectId: subject}},
	}}
}
func usersetUpdate(op v1.RelationshipUpdate_Operation, kind, id, relation, ws, role string) *v1.RelationshipUpdate {
	update := graphUpdate(op, kind, id, relation, "workspace", ws)
	update.Relationship.Subject.OptionalRelation = role
	return update
}

// Joining/removal publishes/revokes the default personal grant; role-only edits preserve it.
// Recovery leaves canonical direct scope grants intact.
func (s *Store) WriteMemberRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID, defaults bool, accounts ...uuid.UUID) error {
	if id == uuid.Nil || len(accounts) == 0 || len(accounts) > 100 {
		return Fault{"VALIDATION"}
	}
	var updates []*v1.RelationshipUpdate
	seen := map[uuid.UUID]bool{}
	for _, account := range accounts {
		if account == uuid.Nil || seen[account] {
			return Fault{"VALIDATION"}
		}
		seen[account] = true
		member, err := s.Member(ctx, id, account)
		if err != nil {
			return err
		}
		for _, role := range workspaceRoles {
			op := v1.RelationshipUpdate_OPERATION_DELETE
			if member.Status == "active" && member.Role == role {
				op = v1.RelationshipUpdate_OPERATION_TOUCH
			}
			updates = append(updates, graphUpdate(op, "workspace", id.String(), role, "account", account.String()))
		}
		if defaults {
			op := v1.RelationshipUpdate_OPERATION_TOUCH
			if member.Status != "active" {
				op = v1.RelationshipUpdate_OPERATION_DELETE
			}
			updates = append(updates, graphUpdate(op, "scope", member.PersonalScopeID.String(), "manager", "account", account.String()))
		}
	}
	_, err := graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: updates})
	return err
}
func (s *Store) PublishStorageRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID) error {
	var fs, shared uuid.UUID
	var status string
	if err := s.DB.QueryRow(ctx, `SELECT filesystem_id,shared_scope_id,status FROM workspaces WHERE id=$1`, id).Scan(&fs, &shared, &status); err != nil {
		return err
	}
	op := v1.RelationshipUpdate_OPERATION_TOUCH
	if status == "deleted" {
		op = v1.RelationshipUpdate_OPERATION_DELETE
	}
	updates := []*v1.RelationshipUpdate{}
	for _, role := range workspaceRoles {
		updates = append(updates, usersetUpdate(op, "filesystem", fs.String(), "reader", id.String(), role))
	}
	updates = append(updates, usersetUpdate(op, "filesystem", fs.String(), "deleter", id.String(), "owner"), usersetUpdate(op, "scope", shared.String(), "manager", id.String(), "owner"), usersetUpdate(op, "scope", shared.String(), "manager", id.String(), "admin"), usersetUpdate(op, "scope", shared.String(), "editor", id.String(), "member"))
	_, err := graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: updates})
	return err
}
func (s *Store) RemoveRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID) error {
	rows, err := s.DB.Query(ctx, `SELECT personal_scope_id FROM workspace_members WHERE workspace_id=$1`, id)
	if err != nil {
		return err
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return err
	}
	var fs, shared uuid.UUID
	if err = s.DB.QueryRow(ctx, `SELECT filesystem_id,shared_scope_id FROM workspaces WHERE id=$1`, id).Scan(&fs, &shared); err != nil {
		return err
	}
	ids = append(ids, shared)
	for _, scope := range ids {
		if _, err = graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "scope", OptionalResourceId: scope.String()}}); err != nil {
			return err
		}
	}
	for kind, resource := range map[string]uuid.UUID{"filesystem": fs, "workspace": id} {
		if _, err = graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: kind, OptionalResourceId: resource.String()}}); err != nil {
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
func (s *Store) RebuildWorkspaceRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID) error {
	var status string
	if err := s.DB.QueryRow(ctx, `SELECT status FROM workspaces WHERE id=$1`, id).Scan(&status); err != nil {
		return err
	}
	if status == "deleted" {
		return s.RemoveRelationships(ctx, graph, id)
	}
	for _, role := range workspaceRoles {
		if _, err := graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: id.String(), OptionalRelation: role}}); err != nil {
			return err
		}
	}
	after := uuid.Nil
	for {
		rows, err := s.DB.Query(ctx, `SELECT account_id FROM workspace_members WHERE workspace_id=$1 AND account_id>$2 ORDER BY account_id LIMIT 100`, id, after)
		if err != nil {
			return err
		}
		ids, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
		if err != nil {
			return err
		}
		if len(ids) == 0 {
			break
		}
		if err = s.WriteMemberRelationships(ctx, graph, id, false, ids...); err != nil {
			return err
		}
		after = ids[len(ids)-1]
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
func (s *Service) ChangeScopeAccess(ctx context.Context, ws, actor, scope, target uuid.UUID, role string, revoke bool) (Workspace, error) {
	if role != "manager" && role != "editor" && role != "viewer" {
		return Workspace{}, Fault{"VALIDATION"}
	}
	var owned bool
	if err := s.Store.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM workspaces WHERE id=$1 AND status='active' AND (shared_scope_id=$2 OR EXISTS(SELECT 1 FROM workspace_members WHERE workspace_id=$1 AND personal_scope_id=$2)))`, ws, scope).Scan(&owned); err != nil {
		return Workspace{}, err
	}
	if !owned {
		return Workspace{}, Fault{"NOT_FOUND"}
	}
	allowed, err := authz.Check(ctx, s.Store.Graph, actor.String(), authz.ScopeManageAccess, authz.Resource{Type: "scope", ID: scope.String()})
	if err != nil {
		return Workspace{}, err
	}
	if !allowed {
		return Workspace{}, Fault{"FORBIDDEN"}
	}
	if _, err = s.Accounts.Summaries(ctx, []uuid.UUID{target}); err != nil {
		return Workspace{}, err
	}
	return s.Mutate(ctx, Mutation{Kind: "scope", WorkspaceID: ws, ActorID: actor, ScopeID: scope, TargetID: target, ScopeRole: role, Revoke: revoke})
}
func (s *Service) UpdateScopeAccess(ctx context.Context, in Mutation) (Workspace, error) {
	var status string
	if err := s.Store.DB.QueryRow(ctx, `SELECT status FROM workspaces WHERE id=$1`, in.WorkspaceID).Scan(&status); err != nil {
		return Workspace{}, err
	}
	if status != "active" {
		return Workspace{}, Fault{"WORKSPACE_DELETING"}
	}
	op := v1.RelationshipUpdate_OPERATION_TOUCH
	if in.Revoke {
		op = v1.RelationshipUpdate_OPERATION_DELETE
	}
	_, err := s.Store.Graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{graphUpdate(op, "scope", in.ScopeID.String(), in.ScopeRole, "account", in.TargetID.String())}})
	return Workspace{ID: in.WorkspaceID}, err
}
