package filesystem

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"openlet/apps/letfs/internal/storage"
)

func (s *Store) expireUpload(ctx context.Context, fs, id uuid.UUID) error {
	session, err := s.lifecycleSession(ctx, fs)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	changed, err := session.tx.Exec(ctx, `UPDATE uploads SET state='aborted',inline_bytes=NULL,updated_at=now()
 WHERE id=$1 AND filesystem_id=$2 AND state IN ('open','completing') AND expires_at<=now()`, id, fs)
	if err != nil {
		return databaseError(err)
	}
	if changed.RowsAffected() == 1 {
		if err = session.queueCandidate(ctx, id); err != nil {
			return err
		}
		if err = session.completeUploadReceipt(ctx, id); err != nil {
			return err
		}
	}
	return databaseError(session.tx.Commit(ctx))
}

func (s *Store) ExpireUploads(ctx context.Context) (int, error) {
	rows, err := s.DB.Query(ctx, `SELECT id,filesystem_id FROM uploads WHERE state IN ('open','completing') AND expires_at<=now() ORDER BY expires_at,id LIMIT 64`)
	if err != nil {
		return 0, databaseError(err)
	}
	type expired struct{ id, fs uuid.UUID }
	items, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (expired, error) {
		var item expired
		err := row.Scan(&item.id, &item.fs)
		return item, err
	})
	if err != nil {
		return 0, databaseError(err)
	}
	for _, item := range items {
		if err := s.expireUpload(ctx, item.fs, item.id); err != nil {
			return 0, err
		}
	}
	rows, err = s.DB.Query(ctx, `SELECT id,candidate_key,multipart_id FROM uploads WHERE state='aborted' AND multipart_id IS NOT NULL ORDER BY updated_at,id LIMIT 64`)
	if err != nil {
		return 0, databaseError(err)
	}
	type multipart struct {
		id          uuid.UUID
		key, remote string
	}
	pending, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (multipart, error) {
		var item multipart
		err := row.Scan(&item.id, &item.key, &item.remote)
		return item, err
	})
	if err != nil {
		return 0, databaseError(err)
	}
	for _, item := range pending {
		if err := s.abortMultipart(ctx, item.id, item.key, item.remote); err != nil {
			return 0, err
		}
	}
	return len(items), nil
}

// DeleteObjects commits the claim before S3 I/O and keeps ambiguous-write tombstones.
func (s *Store) DeleteObjects(ctx context.Context) (int, error) {
	rows, err := s.DB.Query(ctx, `SELECT object_key,bucket_id FROM object_deletions WHERE eligible_at<=now()
 AND (state!='deleted' OR ambiguous_write OR open_writes>0) ORDER BY eligible_at,object_key LIMIT 64`)
	if err != nil {
		return 0, databaseError(err)
	}
	type candidate struct {
		key    string
		bucket uuid.UUID
	}
	items, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (candidate, error) {
		var item candidate
		err := row.Scan(&item.key, &item.bucket)
		return item, err
	})
	if err != nil {
		return 0, databaseError(err)
	}
	deadline := time.Now().Add(180 * time.Second)
	count := 0
	for _, item := range items {
		if !time.Now().Before(deadline) {
			break
		}
		claimed, err := s.claimObjectDeletion(ctx, item.key, item.bucket)
		if err != nil {
			return count, err
		}
		if !claimed {
			continue
		}
		remote, cancel := context.WithDeadline(ctx, minTime(time.Now().Add(120*time.Second), deadline))
		if s.Storage == nil {
			err = storage.ErrUnavailable
		} else {
			err = s.Storage.Delete(remote, item.key)
		}
		cancel()
		if err != nil && !errors.Is(err, storage.ErrNotFound) {
			return count, storageError(ctx, err)
		}
		_, err = s.DB.Exec(ctx, `UPDATE object_deletions SET state='deleted',eligible_at=now()+interval '1 day',updated_at=now()
 WHERE object_key=$1 AND state='deleting'`, item.key)
		if err != nil {
			return count, databaseError(err)
		}
		count++
	}
	return count, nil
}

func minTime(a, b time.Time) time.Time {
	if a.Before(b) {
		return a
	}
	return b
}

func (s *Store) claimObjectDeletion(ctx context.Context, key string, bucket uuid.UUID) (bool, error) {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return false, databaseError(err)
	}
	defer tx.Rollback(ctx)
	var id uuid.UUID
	if err = tx.QueryRow(ctx, `SELECT id FROM quota_buckets WHERE id=$1 FOR UPDATE`, bucket).Scan(&id); err != nil {
		return false, databaseError(err)
	}
	changed, err := tx.Exec(ctx, `UPDATE object_deletions d SET state='deleting',eligible_at=now()+interval '15 minutes',updated_at=now()
 WHERE d.object_key=$1 AND d.eligible_at<=now() AND (d.state!='deleted' OR d.ambiguous_write OR d.open_writes>0)
 AND NOT EXISTS(SELECT 1 FROM files WHERE object_key=d.object_key)
 AND NOT EXISTS(SELECT 1 FROM uploads WHERE candidate_key=d.object_key AND state IN ('open','completing'))`, key)
	if err != nil {
		return false, databaseError(err)
	}
	if changed.RowsAffected() == 0 {
		if _, err = tx.Exec(ctx, `UPDATE object_deletions SET eligible_at=now()+interval '15 minutes' WHERE object_key=$1 AND eligible_at<=now()`, key); err != nil {
			return false, databaseError(err)
		}
	}
	return changed.RowsAffected() == 1, databaseError(tx.Commit(ctx))
}
