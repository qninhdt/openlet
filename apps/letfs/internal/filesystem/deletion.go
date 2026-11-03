package filesystem

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type DeletionInput struct {
	FilesystemID uuid.UUID  `json:"filesystem_id"`
	EntryID      *uuid.UUID `json:"entry_id"`
}

func (in DeletionInput) WorkflowID() string {
	if in.EntryID != nil {
		return "purge-trash/" + in.FilesystemID.String() + "/" + in.EntryID.String()
	}
	return "delete-filesystem/" + in.FilesystemID.String()
}

// PrepareTrashPurge persists admission; the workflow dispatcher owns scheduling.
func (s *Store) PrepareTrashPurge(ctx context.Context, fs, id uuid.UUID) (*TrashEntry, error) {
	if _, err := s.authorize(ctx, fs, "filesystem", authz.TrashPurge); err != nil {
		return nil, err
	}
	if id == uuid.Nil {
		return nil, apperr.New(apperr.Invalid, "VALIDATION", "entry identity required")
	}
	session, err := s.lifecycleSession(ctx, fs)
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
		if err = session.tx.QueryRow(ctx, `SELECT state FROM quota_buckets WHERE id=$1`, session.bucket).Scan(&state); err != nil {
			return nil, databaseError(err)
		}
		if state != "active" {
			return nil, apperr.New(apperr.Conflict, "BUCKET_FROZEN", "bucket is frozen")
		}
		if _, err = session.tx.Exec(ctx, `UPDATE trash_entries SET state='purging' WHERE id=$1`, id); err != nil {
			return nil, databaseError(err)
		}
		entry.Status = "purging"
	}
	return &entry, databaseError(session.tx.Commit(ctx))
}

func (s *Store) PrepareFilesystemDeletion(ctx context.Context, fs uuid.UUID) error {
	_, err := service(ctx)
	if err != nil {
		return err
	}
	session, err := s.lifecycleSession(ctx, fs)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	if _, err = bucketForUpdate(ctx, session.tx, session.bucket); err != nil {
		return databaseError(err)
	}
	var state string
	if err = session.tx.QueryRow(ctx, `SELECT state FROM filesystems WHERE id=$1`, fs).Scan(&state); err != nil {
		return databaseError(err)
	}
	if state != "active" {
		return nil
	}
	if _, err = session.tx.Exec(ctx, `UPDATE filesystems SET state='deleting' WHERE id=$1`, fs); err != nil {
		return databaseError(err)
	}
	if _, err = session.tx.Exec(ctx, `INSERT INTO index_deletions(file_id,generation)
 SELECT f.node_id,f.desired_generation FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.filesystem_id=$1 AND f.desired_generation>0 ON CONFLICT DO NOTHING`, fs); err != nil {
		return databaseError(err)
	}
	if _, err = session.tx.Exec(ctx, `UPDATE idempotency_keys SET expires_at=now()+interval '24 hours'
 WHERE operation='copy-node' AND result->>'filesystem_id'=$1 AND expires_at IS NULL`, fs.String()); err != nil {
		return databaseError(err)
	}
	if _, err = session.tx.Exec(ctx, `INSERT INTO object_deletions(object_key,bucket_id,ambiguous_write,eligible_at)
 SELECT candidate_key,bucket_id,true,greatest(now()+interval '15 minutes',transfer_deadline) FROM uploads
 WHERE filesystem_id=$1 AND result_node_id IS NULL AND candidate_key IS NOT NULL ON CONFLICT(object_key) DO UPDATE
 SET ambiguous_write=true,eligible_at=greatest(object_deletions.eligible_at,excluded.eligible_at)`, fs); err != nil {
		return databaseError(err)
	}
	if _, err = session.tx.Exec(ctx, `UPDATE uploads SET state=CASE WHEN state IN ('open','completing') THEN 'aborted' ELSE state END,
 inline_bytes=NULL,updated_at=now() WHERE filesystem_id=$1 AND result_node_id IS NULL`, fs); err != nil {
		return databaseError(err)
	}
	if _, err = session.tx.Exec(ctx, `UPDATE idempotency_keys r SET expires_at=now()+interval '24 hours' FROM uploads u
 WHERE u.filesystem_id=$1 AND u.state='aborted' AND r.operation='create-upload' AND r.result->>'id'=u.id::text AND r.expires_at IS NULL`, fs); err != nil {
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
 WHERE n.filesystem_id=$1 AND f.node_id=ANY($2) AND f.desired_generation>0`, s.fs, ids)
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
	if _, err = s.tx.Exec(ctx, `INSERT INTO object_deletions(object_key,bucket_id)
 SELECT f.object_key,$2 FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.id=ANY($1) AND n.filesystem_id=$3 AND f.object_key IS NOT NULL
 ON CONFLICT(object_key) DO UPDATE SET eligible_at=least(object_deletions.eligible_at,excluded.eligible_at)`, ids, s.bucket, s.fs); err != nil {
		return databaseError(err)
	}
	if _, err = s.tx.Exec(ctx, `DELETE FROM trash_entries WHERE filesystem_id=$1 AND node_id=ANY($2)`, s.fs, ids); err != nil {
		return databaseError(err)
	}
	if _, err = s.tx.Exec(ctx, `UPDATE trash_entries SET original_parent_id=NULL WHERE filesystem_id=$1 AND original_parent_id=ANY($2)`, s.fs, ids); err != nil {
		return databaseError(err)
	}
	rows, err = s.tx.Query(ctx, `DELETE FROM nodes WHERE filesystem_id=$1 AND id=ANY($2) RETURNING size_bytes`, s.fs, ids)
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
 SELECT id,parent_id,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2 UNION ALL
 SELECT n.id,n.parent_id,b.depth+1 FROM branch b JOIN LATERAL (
 SELECT id,parent_id FROM nodes WHERE filesystem_id=$2 AND parent_id=b.id ORDER BY name LIMIT 1) n ON true WHERE b.depth<128)
 SELECT id,parent_id FROM branch ORDER BY depth DESC LIMIT 1`, root, s.fs).Scan(&leaf, &parent)
	if errors.Is(err, pgx.ErrNoRows) {
		return []uuid.UUID{}, nil
	}
	if err != nil {
		return nil, databaseError(err)
	}
	rows, err := s.tx.Query(ctx, `SELECT n.id FROM nodes n WHERE n.filesystem_id=$1 AND (n.id=$2 OR n.parent_id=$3)
 AND NOT EXISTS(SELECT 1 FROM nodes c WHERE c.filesystem_id=$1 AND c.parent_id=n.id) ORDER BY n.name LIMIT 64`, s.fs, leaf, parent)
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
func (s *Store) DeletionBatch(ctx context.Context, fs uuid.UUID, entryID *uuid.UUID) (bool, error) {
	if fs == uuid.Nil || entryID != nil && *entryID == uuid.Nil {
		return false, apperr.New(apperr.Invalid, "VALIDATION", "deletion identities required")
	}
	session, err := s.lifecycleSession(ctx, fs)
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
		if err = session.tx.QueryRow(ctx, `SELECT state FROM filesystems WHERE id=$1`, fs).Scan(&state); err != nil {
			return false, databaseError(err)
		}
		if state == "deleted" {
			return true, nil
		}
		if state != "deleting" {
			return false, apperr.New(apperr.Conflict, "FILESYSTEM_NOT_DELETING", "filesystem is not deleting")
		}
		rows, err := session.tx.Query(ctx, `SELECT n.id FROM nodes n WHERE n.filesystem_id=$1
 AND NOT EXISTS(SELECT 1 FROM nodes c WHERE c.filesystem_id=$1 AND c.parent_id=n.id) ORDER BY n.id LIMIT 64`, fs)
		if err != nil {
			return false, databaseError(err)
		}
		ids, err = pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
		if err != nil {
			return false, databaseError(err)
		}
		for _, id := range ids {
			if id == session.root {
				if _, err = session.tx.Exec(ctx, `UPDATE filesystems SET root_id=NULL WHERE id=$1`, fs); err != nil {
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
		err = session.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM trash_entries WHERE filesystem_id=$1 AND id=$2)`, fs, *entryID).Scan(&remaining)
	} else {
		err = session.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM nodes WHERE filesystem_id=$1)`, fs).Scan(&remaining)
	}
	if err != nil {
		return false, databaseError(err)
	}
	if entryID == nil && !remaining {
		if _, err = session.tx.Exec(ctx, `UPDATE filesystems SET state='deleted',root_id=NULL WHERE id=$1 AND node_count=0`, fs); err != nil {
			return false, databaseError(err)
		}
	}
	return !remaining, databaseError(session.tx.Commit(ctx))
}

// FilesystemDeleted reports completion only after the owner committed all cleanup.
func (s *Store) FilesystemDeleted(ctx context.Context, id uuid.UUID) (bool, error) {
	if _, err := service(ctx); err != nil {
		return false, err
	}
	var completed bool
	err := s.DB.QueryRow(ctx, `SELECT state='deleted' FROM filesystems WHERE id=$1`, id).Scan(&completed)
	return completed, databaseError(err)
}
