package filesystem

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/search"
)

type IndexDeletion struct {
	Source Generation
}

func (s *Store) IndexDeletionCandidates(ctx context.Context) ([]IndexDeletion, error) {
	rows, err := s.DB.Query(ctx, `SELECT d.file_id,d.generation FROM index_deletions d WHERE d.eligible_at<=now()
 AND NOT EXISTS(SELECT 1 FROM files f WHERE f.node_id=d.file_id AND f.desired_generation=d.generation AND f.publication_status IN ('enriched','ready')) ORDER BY d.eligible_at,d.file_id LIMIT 32`)
	if err != nil {
		return nil, databaseError(err)
	}
	items, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (IndexDeletion, error) {
		var item IndexDeletion
		err := row.Scan(&item.Source.FileID, &item.Source.Generation)
		return item, err
	})
	return items, databaseError(err)
}

func (s *Store) DeleteObsoleteIndex(ctx context.Context, item IndexDeletion) (bool, error) {
	if err := s.IndexSpace.Validate(); err != nil {
		return false, err
	}
	var fs uuid.UUID
	err := s.DB.QueryRow(ctx, `SELECT filesystem_id FROM nodes WHERE id=$1`, item.Source.FileID).Scan(&fs)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return false, databaseError(err)
	}
	var guard *session
	if err == nil {
		guard, err = s.lifecycleSession(ctx, fs)
		if err != nil {
			return false, err
		}
		defer guard.tx.Rollback(ctx)
		var active bool
		err = guard.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM files WHERE node_id=$1 AND desired_generation=$2 AND publication_status IN ('enriched','ready'))`, item.Source.FileID, item.Source.Generation).Scan(&active)
		if err != nil {
			return false, databaseError(err)
		}
		if active {
			return false, nil
		}
	}
	// Keep the existing lifecycle lock across the bounded remote delete and final state check.
	if s.Search == nil {
		return false, search.Dependency()
	}
	if err = s.Search.DeletePoints(ctx, s.IndexSpace.Collection, item.Source.FileID, item.Source.Generation, s.IndexSpace.Model, s.IndexSpace.Dimension); err != nil {
		return false, err
	}
	if guard != nil {
		if err = guard.tx.Commit(ctx); err != nil {
			return false, databaseError(err)
		}
	}
	// An old remote upsert can outlive its producer, so revisit its compact tombstone.
	_, err = s.DB.Exec(ctx, `UPDATE index_deletions SET eligible_at=now()+interval '1 day' WHERE file_id=$1 AND generation=$2 `,
		item.Source.FileID, item.Source.Generation)
	return err == nil, databaseError(err)
}
