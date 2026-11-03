package workspace

import (
	"context"
	"errors"
	"io"
	"slices"
	"strings"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// SyncRelationships derives access from current business records, never an old role command.
func (s *Store) SyncRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID) error {
	if id == uuid.Nil {
		return Fault{"VALIDATION"}
	}
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	// Read graph before SQL: any observed published state already has a canonical commit.
	stream, err := graph.ReadRelationships(ctx, &v1.ReadRelationshipsRequest{
		Consistency:        &v1.Consistency{Requirement: &v1.Consistency_FullyConsistent{FullyConsistent: true}},
		RelationshipFilter: &v1.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: id.String(), OptionalRelation: "grant"},
		OptionalLimit:      4,
	})
	if err != nil {
		return err
	}
	var previous []*v1.Relationship
	for {
		response, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return err
		}
		grant := response.Relationship
		if len(previous) == 3 || !strings.HasPrefix(grant.Subject.Object.ObjectId, id.String()+"/") {
			return Fault{"STATE_CONFLICT"}
		}
		previous = append(previous, grant)
	}
	value, members, err := s.relationshipState(ctx, id)
	if err != nil {
		return err
	}
	// Role groups are immutable for an existing business revision/lifecycle state.
	// Stage them before one atomic switch; no new SQL revision or graph marker is needed.
	prefix := id.String() + "/" + value.Revision + "/" + value.Status + "/"
	var staged, publish []*v1.RelationshipUpdate
	for _, role := range []string{"owner", "editor", "viewer"} {
		staged = append(staged, graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "role_grant", prefix+role, "role", "role", role))
		publish = append(publish, graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "workspace", id.String(), "grant", "role_grant", prefix+role))
	}
	for _, member := range members {
		staged = append(staged, graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "role_grant", prefix+member.Role, "member", "user", member.UserID.String()))
	}
	for len(staged) > 0 {
		n := min(len(staged), 1000)
		if _, err = graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: staged[:n]}); err != nil {
			return err
		}
		staged = staged[n:]
	}
	filter := &v1.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: id.String(), OptionalRelation: "grant"}
	condition := &v1.Precondition{Operation: v1.Precondition_OPERATION_MUST_NOT_MATCH, Filter: filter}
	if len(previous) > 0 {
		condition.Operation = v1.Precondition_OPERATION_MUST_MATCH
		filter.OptionalSubjectFilter = &v1.SubjectFilter{SubjectType: "role_grant", OptionalSubjectId: previous[0].Subject.Object.ObjectId}
	}
	var retired []string
	for _, grant := range previous {
		old := grant.Subject.Object.ObjectId
		if !slices.Contains([]string{prefix + "owner", prefix + "editor", prefix + "viewer"}, old) {
			publish = append(publish, &v1.RelationshipUpdate{Operation: v1.RelationshipUpdate_OPERATION_DELETE, Relationship: grant})
			retired = append(retired, old)
		}
	}
	operation := v1.RelationshipUpdate_OPERATION_DELETE
	if value.Status == "active" {
		operation = v1.RelationshipUpdate_OPERATION_TOUCH
	}
	publish = append(publish, graphUpdate(operation, "workspace", id.String(), "enabled", "user", "*"))
	if value.BucketID != nil {
		publish = append(publish, graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "quota_bucket", value.BucketID.String(), "workspace", "workspace", id.String()))
	}
	if value.FilesystemID != nil {
		publish = append(publish, graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "filesystem", value.FilesystemID.String(), "workspace", "workspace", id.String()))
	}
	if _, err = graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: publish, OptionalPreconditions: []*v1.Precondition{condition}}); err != nil {
		return err
	}
	for _, group := range retired {
		if _, err = graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "role_grant", OptionalResourceId: group}}); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) relationshipState(ctx context.Context, id uuid.UUID) (Workspace, []Member, error) {
	var value Workspace
	tx, err := s.DB.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return value, nil, err
	}
	defer tx.Rollback(ctx)
	err = tx.QueryRow(ctx, `SELECT id,revision::text,status,quota_bucket_id,filesystem_id FROM workspaces WHERE id=$1`, id).
		Scan(&value.ID, &value.Revision, &value.Status, &value.BucketID, &value.FilesystemID)
	if errors.Is(err, pgx.ErrNoRows) {
		return value, nil, Fault{"NOT_FOUND"}
	}
	if err != nil {
		return value, nil, err
	}
	rows, err := tx.Query(ctx, `SELECT user_id,role FROM workspace_members WHERE workspace_id=$1 ORDER BY user_id`, id)
	if err != nil {
		return value, nil, err
	}
	members, err := pgx.CollectRows(rows, pgx.RowToStructByPos[Member])
	if err != nil {
		return value, nil, err
	}
	owners := 0
	for _, member := range members {
		if member.Role == "owner" {
			owners++
		}
	}
	if owners != 1 {
		return value, nil, Fault{"STATE_CONFLICT"}
	}
	return value, members, tx.Commit(ctx)
}

func graphUpdate(operation v1.RelationshipUpdate_Operation, resourceType, resource, relation, subjectType, subject string) *v1.RelationshipUpdate {
	return &v1.RelationshipUpdate{Operation: operation, Relationship: &v1.Relationship{
		Resource: &v1.ObjectReference{ObjectType: resourceType, ObjectId: resource}, Relation: relation,
		Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: subjectType, ObjectId: subject}},
	}}
}

// RelationshipIDs includes retained nonactive identities for rebuild and retry recovery.
func (s *Store) RelationshipIDs(ctx context.Context, after uuid.UUID) ([]uuid.UUID, error) {
	rows, err := s.DB.Query(ctx, `SELECT id FROM workspaces WHERE id>$1 ORDER BY id LIMIT 100`, after)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
}

// RebuildRelationships runs with owner writers stopped by the recovery command.
func (s *Store) RebuildRelationships(ctx context.Context, graph v1.PermissionsServiceClient) error {
	after := uuid.Nil
	for {
		page, cancel := context.WithTimeout(ctx, 30*time.Second)
		ids, err := s.RelationshipIDs(page, after)
		cancel()
		if err != nil {
			return err
		}
		for _, id := range ids {
			item, cancel := context.WithTimeout(ctx, 2*time.Minute)
			err = s.SyncRelationships(item, graph, id)
			if err == nil {
				err = s.CleanupRelationships(item, graph, id)
			}
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
