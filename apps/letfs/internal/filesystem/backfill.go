package filesystem

import (
	"context"
	"crypto/sha256"
	"encoding/hex"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type BackfillCandidate struct {
	FilesystemID uuid.UUID
	Name         string
	Revision     int64
	Dispatch     ProcessingDispatch
}

func (s *Store) BackfillCandidates(ctx context.Context, mode string, after uuid.UUID, limit int) ([]BackfillCandidate, error) {
	if mode != "missing" && mode != "rebuild-index" || limit < 1 || limit > 1000 {
		return nil, enrichmentValidation("invalid backfill mode or limit")
	}
	rows, err := s.DB.Query(ctx, `WITH RECURSIVE live AS (
 SELECT n.id,n.filesystem_id,n.kind,0 AS depth FROM nodes n JOIN filesystems fs ON fs.root_id=n.id JOIN quota_buckets b ON b.id=fs.bucket_id WHERE fs.state='active' AND b.state='active'
 UNION ALL SELECT n.id,n.filesystem_id,n.kind,l.depth+1 FROM nodes n JOIN live l ON n.parent_id=l.id AND n.filesystem_id=l.filesystem_id WHERE l.kind='directory' AND l.depth<128)
 SELECT n.filesystem_id,n.name,n.revision,f.node_id,f.desired_generation,f.publication_status,f.index_status,f.processing_updated_at
 FROM live l JOIN nodes n ON n.id=l.id JOIN files f ON f.node_id=n.id WHERE n.id>$1
 AND (($2='missing' AND f.index_status!='ready') OR ($2='rebuild-index' AND f.publication_status='ready')) ORDER BY n.id LIMIT $3`, after, mode, limit+1)
	if err != nil {
		return nil, databaseError(err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (BackfillCandidate, error) {
		var c BackfillCandidate
		err := row.Scan(&c.FilesystemID, &c.Name, &c.Revision, &c.Dispatch.Source.FileID, &c.Dispatch.Source.Generation, &c.Dispatch.Publication, &c.Dispatch.IndexStatus, &c.Dispatch.UpdatedAt)
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
	session, err := s.openSession(ctx, c.FilesystemID, true)
	if err != nil {
		return false, err
	}
	defer session.tx.Rollback(ctx)
	id := c.Dispatch.Source.FileID
	node, err := session.resolveOne(ctx, []Mount{{Path: "/", FilesystemID: c.FilesystemID}}, Locator{NodeID: &id})
	if err != nil {
		return false, err
	}
	if err = node.writable(); err != nil {
		return false, err
	}
	current, err := scanDispatch(session.tx.QueryRow(ctx, `SELECT node_id,desired_generation,publication_status,index_status,processing_updated_at FROM files WHERE node_id=$1 FOR UPDATE`, id))
	if err != nil {
		return false, err
	}
	if node.Revision != c.Revision || !c.Eligible() || current.Source != c.Dispatch.Source || current.Publication != c.Dispatch.Publication || current.IndexStatus != c.Dispatch.IndexStatus || !current.UpdatedAt.Equal(c.Dispatch.UpdatedAt) {
		return false, nil
	}
	if current.Publication == "ready" {
		if err = session.enqueueIndexDeletion(ctx, []uuid.UUID{id}); err != nil {
			return false, err
		}
		_, err = session.tx.Exec(ctx, `UPDATE files SET index_status='pending',indexed_generation=NULL,processing_error=NULL,processing_updated_at=now() WHERE node_id=$1`, id)
	} else {
		var object *string
		var content []byte
		if err = session.tx.QueryRow(ctx, `SELECT object_key,inline_bytes FROM files WHERE node_id=$1`, id).Scan(&object, &content); err != nil {
			return false, databaseError(err)
		}
		var source string
		switch {
		case object != nil && content == nil:
			source = "object:" + *object
		case object == nil && content != nil:
			digest := sha256.Sum256(content)
			source = "inline:" + hex.EncodeToString(digest[:])
		default:
			return false, uploadState("INVALID_SOURCE_IDENTITY")
		}
		if err = session.invalidate(ctx, id); err != nil {
			return false, err
		}
		err = session.recordIntent(ctx, node, actor, source)
	}
	if err != nil {
		return false, databaseError(err)
	}
	return true, databaseError(session.tx.Commit(ctx))
}
