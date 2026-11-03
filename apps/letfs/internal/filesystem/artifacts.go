package filesystem

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func processingFormat(name string) (format string, parse bool) {
	index := strings.LastIndexByte(name, '.')
	if index < 0 {
		return "", false
	}
	switch extension := strings.ToLower(name[index+1:]); extension {
	case "pdf", "docx", "xlsx", "pptx":
		return extension, true
	case "csv":
		return "csv", false
	case "png", "jpg", "jpeg", "webp", "gif":
		return "image", false
	case "txt", "md", "markdown", "rst", "json", "jsonl", "yaml", "yml", "xml", "html", "htm", "css", "js", "ts", "tsx", "jsx", "py", "rs", "go", "java", "c", "h", "cpp", "sh", "sql", "log", "toml", "ini", "cfg":
		return "text", false
	default:
		return "", false
	}
}

func (s *session) recordIntent(ctx context.Context, node Node, actor uuid.UUID, identity string) error {
	format, parse := processingFormat(node.Name)
	publication := "not_required"
	var storedFormat *string
	if format != "" {
		storedFormat = &format
		publication = "parsed"
		if parse {
			publication = "pending"
		}
	}
	_, err := s.tx.Exec(ctx, `UPDATE files SET desired_generation=desired_generation+1,processing_actor_id=$2,processing_format=$3,
 processing_source_identity=$4,publication_status=$5,index_status=CASE WHEN $5='not_required' THEN 'not_required' ELSE 'pending' END,
 published_generation=NULL,indexed_generation=NULL,parse_manifest_hash=NULL,publication_manifest_hash=NULL,
 accepted_attempt=0,accepted_attempt_id=NULL,processing_error=NULL,embedding_model=NULL,vector_collection=NULL,vector_dimension=NULL,
 processing_updated_at=now() WHERE node_id=$1`, node.ID, actor, storedFormat, identity, publication)
	return databaseError(err)
}

type Generation struct {
	FileID     uuid.UUID `json:"file_id"`
	Generation int64     `json:"generation"`
}

// Detached roots are durable cleanup intent; trash has its own lifecycle.
func (s *Store) DiscardForests(ctx context.Context) (int, error) {
	rows, err := s.DB.Query(ctx, `SELECT n.id,n.filesystem_id FROM nodes n JOIN filesystems f ON f.id=n.filesystem_id
 WHERE n.parent_id IS NULL AND n.id IS DISTINCT FROM f.root_id
 AND NOT EXISTS(SELECT 1 FROM trash_entries t WHERE t.node_id=n.id) ORDER BY n.filesystem_id,n.id LIMIT 64`)
	if err != nil {
		return 0, databaseError(err)
	}
	type root struct{ id, fs uuid.UUID }
	roots, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (root, error) {
		var item root
		err := row.Scan(&item.id, &item.fs)
		return item, err
	})
	if err != nil {
		return 0, databaseError(err)
	}
	deadline := time.Now().Add(30 * time.Second)
	count := 0
	for _, root := range roots {
		if !time.Now().Before(deadline) {
			break
		}
		removed, err := s.discardForest(ctx, root.fs, root.id)
		if err != nil {
			return count, err
		}
		if removed {
			count++
		}
	}
	return count, nil
}

func (s *Store) discardForest(ctx context.Context, fs, id uuid.UUID) (bool, error) {
	session, err := s.lifecycleSession(ctx, fs)
	if err != nil {
		return false, err
	}
	defer session.tx.Rollback(ctx)
	var detached bool
	err = session.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM nodes n WHERE n.id=$1 AND n.filesystem_id=$2
 AND n.parent_id IS NULL AND n.id!=$3 AND NOT EXISTS(SELECT 1 FROM trash_entries t WHERE t.node_id=n.id))`, id, fs, session.root).Scan(&detached)
	if err != nil {
		return false, databaseError(err)
	}
	if !detached {
		return false, nil
	}
	leaves, err := session.deletionLeaves(ctx, id)
	if err != nil {
		return false, err
	}
	if err = session.removeNodes(ctx, leaves); err != nil {
		return false, err
	}
	return true, databaseError(session.tx.Commit(ctx))
}

func (s *session) enqueueIndexDeletion(ctx context.Context, ids []uuid.UUID) error {
	_, err := s.tx.Exec(ctx, `INSERT INTO index_deletions(file_id,generation,embedding_model,vector_collection,vector_dimension)
 SELECT node_id,desired_generation,embedding_model,vector_collection,vector_dimension FROM files
 WHERE node_id=ANY($1) AND desired_generation>0 AND embedding_model IS NOT NULL AND vector_collection IS NOT NULL AND vector_dimension IS NOT NULL ON CONFLICT DO NOTHING`, ids)
	return databaseError(err)
}

func (s *session) discardUploads(ctx context.Context, source Generation, stage *string) error {
	_, err := s.tx.Exec(ctx, `INSERT INTO object_deletions(object_key,bucket_id,ambiguous_write,eligible_at)
 SELECT candidate_key,bucket_id,write_expires_at IS NOT NULL,greatest(now()+interval '15 minutes',transfer_deadline) FROM uploads
 WHERE processing_file_id=$1 AND processing_generation=$2 AND ($3::text IS NULL OR processing_stage=$3)
 AND result_node_id IS NULL AND candidate_key IS NOT NULL ON CONFLICT(object_key) DO UPDATE
 SET state='pending',ambiguous_write=object_deletions.ambiguous_write OR excluded.ambiguous_write,
 eligible_at=greatest(object_deletions.eligible_at,excluded.eligible_at)`, source.FileID, source.Generation, stage)
	if err != nil {
		return databaseError(err)
	}
	_, err = s.tx.Exec(ctx, `UPDATE uploads SET state=CASE WHEN state IN ('open','completing') THEN 'aborted' ELSE state END,inline_bytes=NULL,updated_at=now()
 WHERE processing_file_id=$1 AND processing_generation=$2 AND ($3::text IS NULL OR processing_stage=$3) AND result_node_id IS NULL`, source.FileID, source.Generation, stage)
	return databaseError(err)
}

func (s *session) completeProcessingReceipt(ctx context.Context, source Generation) error {
	_, err := s.tx.Exec(ctx, `UPDATE idempotency_keys SET completed_at=now(),expires_at=now()+interval '24 hours'
 WHERE operation='process-file' AND result->>'file_id'=$1 AND result->>'generation'=$2 AND completed_at IS NULL`, source.FileID.String(), fmt.Sprint(source.Generation))
	return databaseError(err)
}

func (s *session) invalidate(ctx context.Context, id uuid.UUID) error {
	var generation int64
	err := s.tx.QueryRow(ctx, `SELECT desired_generation FROM files WHERE node_id=$1 FOR UPDATE`, id).Scan(&generation)
	if err != nil {
		return databaseError(err)
	}
	if err = s.enqueueIndexDeletion(ctx, []uuid.UUID{id}); err != nil {
		return err
	}
	source := Generation{FileID: id, Generation: generation}
	if err = s.discardUploads(ctx, source, nil); err != nil {
		return err
	}
	if err = s.completeProcessingReceipt(ctx, source); err != nil {
		return err
	}
	_, err = s.tx.Exec(ctx, `UPDATE files SET title=NULL,description=NULL,semantic_type=NULL,context=NULL,
 publication_status='not_required',published_generation=NULL,indexed_generation=NULL,index_status='not_required',
 processing_error=NULL,processing_updated_at=now() WHERE node_id=$1`, id)
	if err != nil {
		return databaseError(err)
	}
	_, err = s.tx.Exec(ctx, `UPDATE nodes SET parent_id=NULL WHERE filesystem_id=$1 AND parent_id=$2`, s.fs, id)
	return databaseError(err)
}

func (s *session) fenceTrashed(ctx context.Context, root uuid.UUID) error {
	rows, err := s.tx.Query(ctx, `WITH RECURSIVE tree AS (SELECT id,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2
 UNION ALL SELECT n.id,t.depth+1 FROM nodes n JOIN tree t ON n.parent_id=t.id WHERE n.filesystem_id=$2 AND t.depth<128)
 SELECT f.node_id,f.desired_generation FROM tree t JOIN files f ON f.node_id=t.id WHERE f.desired_generation>0 AND f.publication_status!='not_required'`, root, s.fs)
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
	ids := make([]uuid.UUID, len(sources))
	for i, source := range sources {
		ids[i] = source.FileID
	}
	if err = s.enqueueIndexDeletion(ctx, ids); err != nil {
		return err
	}
	for _, source := range sources {
		if err = s.discardUploads(ctx, source, nil); err != nil {
			return err
		}
		_, err = s.tx.Exec(ctx, `UPDATE files SET publication_status=CASE WHEN publication_status='ready' THEN publication_status ELSE 'failed' END,
 index_status=CASE WHEN index_status='ready' THEN index_status ELSE 'failed' END,processing_error='SOURCE_TRASHED',processing_updated_at=now() WHERE node_id=$1`, source.FileID)
		if err != nil {
			return databaseError(err)
		}
		if err = s.completeProcessingReceipt(ctx, source); err != nil {
			return err
		}
	}
	return nil
}
