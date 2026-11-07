package filesystem

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type BackfillCandidate struct {
	ScopeID  uuid.UUID
	Name     string
	Revision int64
	Dispatch ProcessingDispatch
}

func (s *Store) BackfillCandidates(ctx context.Context, mode string, after uuid.UUID, limit int) ([]BackfillCandidate, error) {
	if mode != "missing" && mode != "rebuild-index" || limit < 1 || limit > 1000 {
		return nil, enrichmentValidation("invalid backfill mode or limit")
	}
	rows, err := s.DB.Query(ctx, `WITH RECURSIVE live AS (
 SELECT n.id,n.scope_id,n.kind,n.name,n.revision,0 AS depth FROM nodes n JOIN scopes scopeID ON scopeID.root_id=n.id JOIN filesystems b ON b.id=scopeID.filesystem_id WHERE scopeID.state='active' AND b.state='active'
 UNION ALL SELECT n.id,n.scope_id,n.kind,n.name,n.revision,l.depth+1 FROM nodes n JOIN live l ON n.parent_id=l.id AND n.scope_id=l.scope_id WHERE l.kind='directory' AND l.depth<128)
 SELECT l.scope_id,l.name,l.revision,f.node_id,f.desired_generation,f.publication_status,f.processing_updated_at,scopeID.allow_indexing
 FROM live l JOIN files f ON f.node_id=l.id JOIN scopes scopeID ON scopeID.id=l.scope_id WHERE l.id>$1
 AND (scopeID.allow_indexing OR f.publication_status NOT IN ('enriched','ready'))
 AND (($2='missing' AND f.publication_status!='ready') OR ($2='rebuild-index' AND f.publication_status='ready')) ORDER BY l.id LIMIT $3`, after, mode, limit+1)
	if err != nil {
		return nil, databaseError(err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (BackfillCandidate, error) {
		var c BackfillCandidate
		err := row.Scan(&c.ScopeID, &c.Name, &c.Revision, &c.Dispatch.Source.FileID, &c.Dispatch.Source.Generation, &c.Dispatch.Publication, &c.Dispatch.UpdatedAt, &c.Dispatch.AllowIndexing)
		return c, databaseError(err)
	})
}

func (c BackfillCandidate) Eligible() bool {
	format, _ := processingFormat(c.Name)
	return format != ""
}

// AdmitBackfill revalidates the observation after workflow I/O and commits durable dispatch intent.
func (s *Store) AdmitBackfill(ctx context.Context, c BackfillCandidate, actor uuid.UUID) (bool, error) {
	if actor == uuid.Nil {
		return false, enrichmentValidation("backfill actor required")
	}
	session, err := s.openSession(ctx, c.ScopeID, true)
	if err != nil {
		return false, err
	}
	defer session.tx.Rollback(ctx)
	id := c.Dispatch.Source.FileID
	node, err := session.resolveOne(ctx, Locator{NodeID: &id})
	if err != nil {
		return false, err
	}
	if err = node.writable(); err != nil {
		return false, err
	}
	current, err := scanDispatch(session.tx.QueryRow(ctx, `SELECT node_id,desired_generation,publication_status,processing_updated_at,$2::boolean FROM files WHERE node_id=$1 FOR UPDATE`, id, session.allowIndexing))
	if err != nil {
		return false, err
	}
	if node.Revision != c.Revision || !c.Eligible() || current.Source != c.Dispatch.Source || current.Publication != c.Dispatch.Publication || !current.UpdatedAt.Equal(c.Dispatch.UpdatedAt) {
		return false, nil
	}
	if current.Publication == "ready" {
		if err = session.enqueueIndexDeletion(ctx, []uuid.UUID{id}); err != nil {
			return false, err
		}
		_, err = session.tx.Exec(ctx, `UPDATE files SET publication_status='enriched',processing_error=NULL,processing_updated_at=now() WHERE node_id=$1`, id)
	} else {
		if err = session.invalidate(ctx, id); err != nil {
			return false, err
		}
		err = session.recordIntent(ctx, node)
	}
	if err != nil {
		return false, databaseError(err)
	}
	return true, databaseError(session.tx.Commit(ctx))
}
