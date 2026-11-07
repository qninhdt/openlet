package account

import (
	"context"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// Identity and owner are immutable; rebuild publishes only Account-owned facts.
func (s *Store) SyncRelationships(ctx context.Context, graph v1.PermissionsServiceClient, ids ...uuid.UUID) error {
	if len(ids) == 0 || len(ids) > 100 {
		return Fault{"VALIDATION"}
	}
	seen := make(map[uuid.UUID]bool, len(ids))
	for _, id := range ids {
		if id == uuid.Nil || seen[id] {
			return Fault{"VALIDATION"}
		}
		seen[id] = true
	}
	rows, err := s.DB.Query(ctx, `SELECT id,owner_id FROM accounts WHERE id=ANY($1)`, ids)
	if err != nil {
		return err
	}
	canonical, err := pgx.CollectRows(rows, pgx.RowToStructByPos[struct {
		ID      uuid.UUID
		OwnerID *uuid.UUID
	}])
	if err != nil {
		return err
	}
	if len(canonical) != len(ids) {
		return Fault{"NOT_FOUND"}
	}
	updates := make([]*v1.RelationshipUpdate, 0, len(canonical))
	for _, value := range canonical {
		id := value.ID
		updates = append(updates, &v1.RelationshipUpdate{
			Operation: v1.RelationshipUpdate_OPERATION_TOUCH,
			Relationship: &v1.Relationship{
				Resource: &v1.ObjectReference{ObjectType: "account", ObjectId: id.String()}, Relation: "self",
				Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: "account", ObjectId: id.String()}},
			},
		})
		if value.OwnerID != nil {
			updates = append(updates, &v1.RelationshipUpdate{
				Operation: v1.RelationshipUpdate_OPERATION_TOUCH,
				Relationship: &v1.Relationship{
					Resource: &v1.ObjectReference{ObjectType: "account", ObjectId: id.String()}, Relation: "owner",
					Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: "account", ObjectId: value.OwnerID.String()}},
				},
			})
		}

	}
	_, err = graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: updates})
	return err
}

// RelationshipIDs pages all identities for rebuild and retry recovery.
func (s *Store) RelationshipIDs(ctx context.Context, after uuid.UUID) ([]uuid.UUID, error) {
	rows, err := s.DB.Query(ctx, `SELECT id FROM accounts WHERE id>$1 ORDER BY id LIMIT 100`, after)
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
		if len(ids) > 0 {
			item, cancel := context.WithTimeout(ctx, 30*time.Second)
			err = s.SyncRelationships(item, graph, ids...)
			cancel()
			if err != nil {
				return err
			}
			after = ids[len(ids)-1]
		}
		if len(ids) < 100 {
			return nil
		}
	}
}
