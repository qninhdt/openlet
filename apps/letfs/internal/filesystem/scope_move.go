package filesystem

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/apperr"
)

// transferTree keeps IDs and payloads; the filesystem lock serializes all tree writes.
func (s *session) transferTree(ctx context.Context, node Node, destination *session, parent Node, name string) error {
	type member struct {
		id                uuid.UUID
		name              string
		kind              string
		artifact          bool
		depth             int64
		generation        int64
		publicationStatus string
	}

	rows, err := s.tx.Query(ctx, `WITH RECURSIVE tree AS (
 SELECT id,parent_id,kind,false AS derived,0 AS depth FROM nodes WHERE id=$1 AND scope_id=$2
 UNION ALL SELECT n.id,n.parent_id,n.kind,t.derived OR t.kind='file',t.depth+1
 FROM nodes n JOIN tree t ON n.parent_id=t.id WHERE n.scope_id=$2 AND t.depth<128)
 SELECT n.id,n.name,n.kind,t.derived,t.depth,coalesce(f.desired_generation,0),coalesce(f.publication_status,'')
 FROM tree t JOIN nodes n ON n.id=t.id LEFT JOIN files f ON f.node_id=n.id`, node.ID, s.scopeID)
	if err != nil {
		return databaseError(err)
	}
	members, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (member, error) {
		var m member
		err := row.Scan(&m.id, &m.name, &m.kind, &m.artifact, &m.depth, &m.generation, &m.publicationStatus)
		return m, err
	})
	if err != nil {
		return databaseError(err)
	}

	parentDepth, err := destination.depth(ctx, parent.ID)
	if err != nil {
		return err
	}
	ids := make([]uuid.UUID, len(members))
	for i, m := range members {
		ids[i] = m.id
		if parentDepth+1+m.depth > maxDepth {
			return apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "tree depth limit exceeded")
		}
	}

	if !destination.allowBlobFiles {
		rows, err := s.tx.Query(ctx, `SELECT object_key,COALESCE(inline_bytes,convert_to(text_content,'UTF8')) FROM files WHERE node_id=ANY($1)`, ids)
		if err != nil {
			return databaseError(err)
		}
		for rows.Next() {
			var object *string
			var content []byte
			if err = rows.Scan(&object, &content); err != nil {
				rows.Close()
				return databaseError(err)
			}
			if object != nil {
				rows.Close()
				return apperr.New(apperr.Invalid, "BLOB_FILES_DISABLED", "destination scope does not allow blob files")
			}
			if err = destination.validateInlineText(content); err != nil {
				rows.Close()
				return err
			}
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return databaseError(err)
		}
	}

	if err = s.enqueueIndexDeletion(ctx, ids); err != nil {
		return err
	}
	for _, m := range members {
		if m.artifact || m.kind != "file" {
			continue
		}
		source := Generation{FileID: m.id, Generation: m.generation}
		if err = s.discardUploads(ctx, source); err != nil {
			return err
		}
		if err = s.completeProcessingReceipt(ctx, source); err != nil {
			return err
		}
		fileName := m.name
		if m.id == node.ID {
			fileName = name
		}
		if err = destination.recordIntent(ctx, Node{ID: m.id, Name: fileName}); err != nil {
			return err
		}
		// Reuse completed semantic work; only its scope-specific index needs rebuilding.
		if m.publicationStatus == "ready" || m.publicationStatus == "enriched" || m.publicationStatus == "index_failed" {
			_, err = s.tx.Exec(ctx, `UPDATE files SET publication_status='enriched' WHERE node_id=$1 AND publication_status!='not_required'`, m.id)
		} else {
			_, err = s.tx.Exec(ctx, `UPDATE files SET publication_status='parsed' WHERE node_id=$1 AND publication_status='pending' AND EXISTS(SELECT 1 FROM nodes WHERE parent_id=$1)`, m.id)
		}
		if err != nil {
			return databaseError(err)
		}
	}

	_, err = s.tx.Exec(ctx, `UPDATE nodes SET scope_id=$2,parent_id=CASE WHEN id=$3 THEN $4 ELSE parent_id END,
 name=CASE WHEN id=$3 THEN $5 ELSE name END,revision=revision+1,updated_at=now() WHERE id=ANY($1)`, ids, destination.scopeID, node.ID, parent.ID, name)
	return databaseError(err)
}
