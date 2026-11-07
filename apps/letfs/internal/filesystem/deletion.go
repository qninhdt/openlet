package filesystem

import (
	"context"
	"errors"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type DeletionInput struct {
	FilesystemID uuid.UUID  `json:"filesystem_id"`
	ScopeID      uuid.UUID  `json:"scope_id"`
	EntryID      *uuid.UUID `json:"entry_id"`
}

// PrepareTrashPurge fences restore before request-owned batched removal.
func (s *Store) PrepareTrashPurge(ctx context.Context, scopeID, id uuid.UUID) (*TrashEntry, error) {
	if _, err := s.authorize(ctx, scopeID, "scope", authz.ScopePurge); err != nil {
		return nil, err
	}
	if id == uuid.Nil {
		return nil, apperr.New(apperr.Invalid, "VALIDATION", "entry identity required")
	}
	session, err := s.lifecycleSession(ctx, scopeID)
	if err != nil {
		return nil, err
	}
	defer session.tx.Rollback(ctx)
	entry, err := session.trashEntry(ctx, id, true)
	if errorReason(err) == "NOT_FOUND" {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	if entry.Status == "trashed" {
		var state string
		if err = session.tx.QueryRow(ctx, `SELECT state FROM filesystems WHERE id=$1`, session.filesystemID).Scan(&state); err != nil {
			return nil, databaseError(err)
		}
		if state != "active" {
			return nil, apperr.New(apperr.Conflict, "FILESYSTEM_DELETING", "filesystem is deleting")
		}
		if _, err = session.tx.Exec(ctx, `UPDATE trash_entries SET state='purging' WHERE id=$1`, id); err != nil {
			return nil, databaseError(err)
		}
		entry.Status = "purging"
	}
	return &entry, databaseError(session.tx.Commit(ctx))
}

func (s *Store) fenceScopeDeletion(ctx context.Context, scopeID uuid.UUID) error {
	session, err := s.lifecycleSession(ctx, scopeID)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	if _, err = filesystemForUpdate(ctx, session.tx, session.filesystemID); err != nil {
		return databaseError(err)
	}
	var state string
	if err = session.tx.QueryRow(ctx, `SELECT state FROM scopes WHERE id=$1`, scopeID).Scan(&state); err != nil {
		return databaseError(err)
	}
	if state != "active" {
		return nil
	}
	if _, err = session.tx.Exec(ctx, `UPDATE scopes SET state='deleting' WHERE id=$1`, scopeID); err != nil {
		return databaseError(err)
	}
	if _, err = session.tx.Exec(ctx, `INSERT INTO index_deletions(file_id,generation)
 SELECT f.node_id,f.desired_generation FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.scope_id=$1 AND f.desired_generation>0 ON CONFLICT DO NOTHING`, scopeID); err != nil {
		return databaseError(err)
	}
	if _, err = session.tx.Exec(ctx, `INSERT INTO object_deletions(object_key,filesystem_id,ambiguous_write,eligible_at)
 SELECT candidate_key,$2,true,greatest(now()+interval '15 minutes',transfer_deadline) FROM uploads
 WHERE scope_id=$1 AND result_node_id IS NULL AND candidate_key IS NOT NULL ON CONFLICT(object_key) DO UPDATE
 SET ambiguous_write=true,eligible_at=greatest(object_deletions.eligible_at,excluded.eligible_at)`, scopeID, session.filesystemID); err != nil {
		return databaseError(err)
	}
	if _, err = session.tx.Exec(ctx, `UPDATE uploads SET state=CASE WHEN state IN ('open','completing') THEN 'aborted' ELSE state END,
 inline_bytes=NULL,updated_at=now() WHERE scope_id=$1 AND result_node_id IS NULL`, scopeID); err != nil {
		return databaseError(err)
	}
	if _, err = session.tx.Exec(ctx, `UPDATE idempotency_keys r SET expires_at=now()+interval '24 hours'
 WHERE r.operation='create-upload' AND r.expires_at IS NULL
 AND r.result->>'id'=ANY(ARRAY(SELECT id::text FROM uploads WHERE scope_id=$1 AND state='aborted'))`, scopeID); err != nil {
		return databaseError(err)
	}
	return databaseError(session.tx.Commit(ctx))
}

// removeNodes retains external cleanup evidence before atomically debiting actual usage.
func (s *session) removeNodes(ctx context.Context, ids []uuid.UUID) error {
	if err := s.enqueueIndexDeletion(ctx, ids); err != nil {
		return err
	}
	rows, err := s.tx.Query(ctx, `SELECT f.node_id,f.desired_generation FROM files f JOIN nodes n ON n.id=f.node_id
 WHERE n.scope_id=$1 AND f.node_id=ANY($2) AND f.desired_generation>0`, s.scopeID, ids)
	if err != nil {
		return databaseError(err)
	}
	sources, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (Generation, error) {
		var source Generation
		err := row.Scan(&source.FileID, &source.Generation)
		return source, err
	})
	if err != nil {
		return databaseError(err)
	}
	for _, source := range sources {
		if err = s.discardUploads(ctx, source); err != nil {
			return err
		}
		if err = s.completeProcessingReceipt(ctx, source); err != nil {
			return err
		}
	}
	if _, err = s.tx.Exec(ctx, `INSERT INTO object_deletions(object_key,filesystem_id)
 SELECT f.object_key,$2 FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.id=ANY($1) AND n.scope_id=$3 AND f.object_key IS NOT NULL
 ON CONFLICT(object_key) DO UPDATE SET eligible_at=least(object_deletions.eligible_at,excluded.eligible_at)`, ids, s.filesystemID, s.scopeID); err != nil {
		return databaseError(err)
	}
	if _, err = s.tx.Exec(ctx, `DELETE FROM trash_entries WHERE scope_id=$1 AND node_id=ANY($2)`, s.scopeID, ids); err != nil {
		return databaseError(err)
	}
	if _, err = s.tx.Exec(ctx, `UPDATE trash_entries SET original_parent_id=NULL WHERE scope_id=$1 AND original_parent_id=ANY($2)`, s.scopeID, ids); err != nil {
		return databaseError(err)
	}
	rows, err = s.tx.Query(ctx, `DELETE FROM nodes WHERE scope_id=$1 AND id=ANY($2) RETURNING size_bytes`, s.scopeID, ids)
	if err != nil {
		return databaseError(err)
	}
	sizes, err := pgx.CollectRows(rows, pgx.RowTo[int64])
	if err != nil {
		return databaseError(err)
	}
	var bytes int64
	for _, size := range sizes {
		bytes += size
	}
	if err = s.usage(ctx, -bytes); err != nil {
		return err
	}
	return s.addNodes(ctx, -int64(len(sizes)))
}

func (s *session) deletionLeaves(ctx context.Context, root uuid.UUID) ([]uuid.UUID, error) {
	var leaf uuid.UUID
	var parent *uuid.UUID
	err := s.tx.QueryRow(ctx, `WITH RECURSIVE branch AS (
 SELECT id,parent_id,0 AS depth FROM nodes WHERE id=$1 AND scope_id=$2 UNION ALL
 SELECT n.id,n.parent_id,b.depth+1 FROM branch b JOIN LATERAL (
 SELECT id,parent_id FROM nodes WHERE scope_id=$2 AND parent_id=b.id ORDER BY name LIMIT 1) n ON true WHERE b.depth<128)
 SELECT id,parent_id FROM branch ORDER BY depth DESC LIMIT 1`, root, s.scopeID).Scan(&leaf, &parent)
	if errors.Is(err, pgx.ErrNoRows) {
		return []uuid.UUID{}, nil
	}
	if err != nil {
		return nil, databaseError(err)
	}
	rows, err := s.tx.Query(ctx, `SELECT n.id FROM nodes n WHERE n.scope_id=$1 AND (n.id=$2 OR n.parent_id=$3)
 AND NOT EXISTS(SELECT 1 FROM nodes c WHERE c.scope_id=$1 AND c.parent_id=n.id) ORDER BY n.name LIMIT 64`, s.scopeID, leaf, parent)
	if err != nil {
		return nil, databaseError(err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return nil, databaseError(err)
	}
	if len(ids) == 0 {
		return nil, apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "tree exceeds deletion depth")
	}
	return ids, nil
}

// DeletionBatch is local workflow state work, never a public operation.
func (s *Store) DeletionBatch(ctx context.Context, scopeID uuid.UUID, entryID *uuid.UUID) (bool, error) {
	if scopeID == uuid.Nil || entryID != nil && *entryID == uuid.Nil {
		return false, apperr.New(apperr.Invalid, "VALIDATION", "deletion identities required")
	}
	session, err := s.lifecycleSession(ctx, scopeID)
	if err != nil {
		return false, err
	}
	defer session.tx.Rollback(ctx)
	var ids []uuid.UUID
	if entryID != nil {
		entry, err := session.trashEntry(ctx, *entryID, false)
		if errorReason(err) == "NOT_FOUND" {
			return true, nil
		}
		if err != nil {
			return false, err
		}
		if entry.Status != "purging" {
			return false, apperr.New(apperr.Conflict, "TRASH_NOT_PURGING", "trash entry is not purging")
		}
		ids, err = session.deletionLeaves(ctx, entry.NodeID)
		if err != nil {
			return false, err
		}
	} else {
		var state string
		if err = session.tx.QueryRow(ctx, `SELECT state FROM scopes WHERE id=$1`, scopeID).Scan(&state); err != nil {
			return false, databaseError(err)
		}
		if state == "deleted" {
			return true, nil
		}
		if state != "deleting" {
			return false, apperr.New(apperr.Conflict, "FILESYSTEM_NOT_DELETING", "filesystem is not deleting")
		}
		rows, err := session.tx.Query(ctx, `SELECT n.id FROM nodes n WHERE n.scope_id=$1
 AND NOT EXISTS(SELECT 1 FROM nodes c WHERE c.scope_id=$1 AND c.parent_id=n.id) ORDER BY n.id LIMIT 64`, scopeID)
		if err != nil {
			return false, databaseError(err)
		}
		ids, err = pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
		if err != nil {
			return false, databaseError(err)
		}
		for _, id := range ids {
			if id == session.root {
				if _, err = session.tx.Exec(ctx, `UPDATE scopes SET root_id=NULL WHERE id=$1`, scopeID); err != nil {
					return false, databaseError(err)
				}
				break
			}
		}
	}
	if err = session.removeNodes(ctx, ids); err != nil {
		return false, err
	}
	var remaining bool
	if entryID != nil {
		err = session.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM trash_entries WHERE scope_id=$1 AND id=$2)`, scopeID, *entryID).Scan(&remaining)
	} else {
		err = session.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM nodes WHERE scope_id=$1)`, scopeID).Scan(&remaining)
	}
	if err != nil {
		return false, databaseError(err)
	}
	if entryID == nil && !remaining {
		if _, err = session.tx.Exec(ctx, `UPDATE scopes SET state='deleted',root_id=NULL WHERE id=$1`, scopeID); err != nil {
			return false, databaseError(err)
		}
	}
	return !remaining, databaseError(session.tx.Commit(ctx))
}

func (s *Store) ListScopesForDeletion(ctx context.Context, fs, after uuid.UUID) ([]uuid.UUID, error) {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, databaseError(err)
	}
	defer tx.Rollback(ctx)
	value, err := filesystemForUpdate(ctx, tx, fs)
	if errorReason(err) == "NOT_FOUND" {
		return []uuid.UUID{}, nil
	}
	if err != nil {
		return nil, err
	}
	if value.State == "active" {
		if _, err = tx.Exec(ctx, `UPDATE filesystems SET state='deleting' WHERE id=$1`, fs); err != nil {
			return nil, databaseError(err)
		}
	}
	rows, err := tx.Query(ctx, `SELECT id FROM scopes WHERE filesystem_id=$1 AND state<>'deleted' AND id>$2 ORDER BY id LIMIT 32`, fs, after)
	if err != nil {
		return nil, databaseError(err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return nil, databaseError(err)
	}
	return ids, databaseError(tx.Commit(ctx))
}

func (s *Store) RemoveFilesystem(ctx context.Context, id uuid.UUID) error {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return databaseError(err)
	}
	defer tx.Rollback(ctx)
	if _, err = filesystemForUpdate(ctx, tx, id); errorReason(err) == "NOT_FOUND" {
		return s.removeGraphResource(ctx, "filesystem", id)
	} else if err != nil {
		return err
	}
	changed, err := tx.Exec(ctx, `UPDATE filesystems SET state='deleted' WHERE id=$1 AND node_count=0 AND used_bytes=0 AND NOT EXISTS(SELECT 1 FROM scopes WHERE filesystem_id=$1 AND state<>'deleted')`, id)
	if err != nil {
		return databaseError(err)
	}
	if changed.RowsAffected() != 1 {
		return apperr.New(apperr.Conflict, "DELETION_INCOMPLETE", "filesystem deletion incomplete")
	}
	if err = tx.Commit(ctx); err != nil {
		return databaseError(err)
	}
	return s.removeGraphResource(ctx, "filesystem", id)
}

func (s *Store) DeleteScopeData(ctx context.Context, fs, scope uuid.UUID) error {
	var actual uuid.UUID
	err := s.DB.QueryRow(ctx, `SELECT filesystem_id FROM scopes WHERE id=$1`, scope).Scan(&actual)
	if errors.Is(err, pgx.ErrNoRows) {
		return s.removeGraphResource(ctx, "scope", scope)
	}
	if err != nil {
		return databaseError(err)
	}
	if actual != fs {
		return apperr.New(apperr.Missing, "NOT_FOUND", "resource not found")
	}
	if err = s.fenceScopeDeletion(ctx, scope); err != nil {
		if errorReason(err) == "NOT_FOUND" {
			return s.removeGraphResource(ctx, "scope", scope)
		}
		return err
	}
	for {
		done, err := s.DeletionBatch(ctx, scope, nil)
		if errorReason(err) == "NOT_FOUND" {
			break
		}
		if err != nil {
			return err
		}
		if done {
			break
		}
	}
	return s.removeGraphResource(ctx, "scope", scope)
}
func (s *Store) removeGraphResource(ctx context.Context, kind string, id uuid.UUID) error {
	if s.Graph == nil {
		return nil
	}
	_, err := s.Graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: kind, OptionalResourceId: id.String()}})
	return err
}

func (s *Store) PurgeTrashData(ctx context.Context, in DeletionInput) error {
	if in.EntryID == nil {
		return apperr.New(apperr.Invalid, "VALIDATION", "entry identity required")
	}
	for {
		done, err := s.DeletionBatch(ctx, in.ScopeID, in.EntryID)
		if errorReason(err) == "NOT_FOUND" {
			return nil
		}
		if err != nil {
			return err
		}
		if done {
			return nil
		}
	}
}
