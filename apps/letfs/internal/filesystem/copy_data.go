package filesystem

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/apperr"
)

func copyDeadline(admission CopyAdmission) error {
	if !time.Now().Before(admission.Deadline) {
		return apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "copy deadline exceeded")
	}
	return nil
}
func (s *session) copyNode(ctx context.Context, id uuid.UUID) (Node, error) {
	return s.resolveOne(ctx, Locator{NodeID: &id})
}
func (s *session) copySource(ctx context.Context, item CopyItem, exact bool) (Node, error) {
	node, err := s.copyNode(ctx, item.Source)
	if errorReason(err) == "NOT_FOUND" {
		return Node{}, apperr.New(apperr.Conflict, "SOURCE_REPLACED", "copy source changed")
	}
	if err != nil {
		return Node{}, err
	}
	sameParent := node.ParentID == nil && item.SourceParent == nil || node.ParentID != nil && item.SourceParent != nil && *node.ParentID == *item.SourceParent
	if !sameParent || node.Name != item.SourceName || node.Kind != item.Kind || (exact || node.Kind == "file") && node.Revision != item.Revision {
		return Node{}, apperr.New(apperr.Conflict, "SOURCE_REPLACED", "copy source changed")
	}
	if node.Kind == "file" {
		var object *string
		var content []byte
		if err = s.tx.QueryRow(ctx, `SELECT object_key,inline_bytes FROM files WHERE node_id=$1`, node.ID).Scan(&object, &content); err != nil {
			return Node{}, databaseError(err)
		}
		var digest *string
		if content != nil {
			sum := sha256.Sum256(content)
			value := hex.EncodeToString(sum[:])
			digest = &value
		}
		same := func(a, b *string) bool { return a == nil && b == nil || a != nil && b != nil && *a == *b }
		if !same(object, item.ObjectKey) || !same(digest, item.InlineSHA256) || node.SizeBytes != item.Size {
			return Node{}, apperr.New(apperr.Conflict, "SOURCE_REPLACED", "copy payload changed")
		}
	}
	return node, nil
}
func (s *session) copyActive(ctx context.Context, admission CopyAdmission) error {
	var active bool
	err := s.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM idempotency_keys WHERE operation='copy-node'
 AND scope=$1 AND result->>'id'=$2 AND expires_at IS NULL)`, "scope/"+admission.ScopeID.String()+"/actor/"+admission.ActorID.String(), admission.ID.String()).Scan(&active)
	if err != nil {
		return databaseError(err)
	}
	if !active {
		return apperr.New(apperr.Conflict, "COPY_CLOSED", "copy admission is closed")
	}
	return nil
}
func (s *session) copyCommitted(ctx context.Context, admission CopyAdmission, item CopyItem) (bool, error) {
	parent, err := s.copyNode(ctx, item.Parent)
	if err != nil {
		return false, err
	}
	if s.scopeID == admission.ScopeID {
		if err = s.cycle(ctx, admission.Root.Source, parent.ID); err != nil {
			return false, err
		}
	}
	depth, err := s.depth(ctx, parent.ID)
	if err != nil {
		return false, err
	}
	if depth >= maxDepth {
		return false, apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "tree depth limit exceeded")
	}
	node, err := s.fetch(ctx, item.Destination)
	if err == nil {
		if node.ParentID == nil || *node.ParentID != item.Parent || node.Name != item.Name || node.Kind != item.Kind || node.Revision != 1 || node.SizeBytes != item.Size || parent.Revision-1 != item.ParentRevision {
			return false, apperr.New(apperr.Conflict, "DESTINATION_CHANGED", "copy destination changed")
		}
		return true, nil
	}
	if errorReason(err) != "NOT_FOUND" {
		return false, err
	}
	if parent.Revision != item.ParentRevision {
		return false, apperr.New(apperr.Conflict, "DESTINATION_CHANGED", "copy parent changed")
	}
	if !item.Derived {
		if err = parent.writable(); err != nil {
			return false, err
		}
		if err = parent.directory(); err != nil {
			return false, err
		}
	}
	var occupied bool
	if err = s.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM nodes WHERE scope_id=$1 AND parent_id=$2 AND name=$3)`, s.scopeID, item.Parent, item.Name).Scan(&occupied); err != nil {
		return false, databaseError(err)
	}
	if occupied {
		return false, apperr.New(apperr.Exists, "NAME_CONFLICT", "name already exists")
	}
	return false, nil
}
func (s *session) releaseCopyCandidate(ctx context.Context, key string) error {
	_, err := s.tx.Exec(ctx, `DELETE FROM object_deletions d WHERE object_key=$1 AND open_writes=0 AND NOT ambiguous_write
 AND state='pending' AND EXISTS(SELECT 1 FROM files f WHERE f.object_key=d.object_key)`, key)
	return databaseError(err)
}

func (s *session) validateCopyCandidate(ctx context.Context, admission CopyAdmission, item CopyItem, key string) (bool, error) {
	if err := copyDeadline(admission); err != nil {
		return false, err
	}
	if err := s.copyActive(ctx, admission); err != nil {
		return false, err
	}
	var active, attempted bool
	if err := s.tx.QueryRow(ctx, `SELECT f.state='active' AND b.state='active' FROM scopes f JOIN filesystems b ON b.id=f.filesystem_id WHERE f.id=$1`, s.scopeID).Scan(&active); err != nil {
		return false, databaseError(err)
	}
	if !active {
		return false, apperr.New(apperr.Conflict, "FILESYSTEM_DELETING", "filesystem is deleting")
	}
	if err := s.tx.QueryRow(ctx, `SELECT state!='pending' FROM object_deletions WHERE object_key=$1`, key).Scan(&attempted); err != nil {
		return false, databaseError(err)
	}
	if attempted {
		return false, apperr.New(apperr.Conflict, "COPY_CANDIDATE_CLOSED", "copy candidate cleanup already started")
	}
	done, err := s.copyCommitted(ctx, admission, item)
	if err != nil || done {
		return done, err
	}
	sourceSession, err := s.inScope(ctx, admission.ScopeID)
	if err != nil {
		return false, err
	}
	_, err = sourceSession.copySource(ctx, item, true)
	return false, err
}

// commitCopyItem consumes trusted workflow selections, not caller-supplied objects.
func (s *Store) commitCopyItem(ctx context.Context, admission CopyAdmission, item CopyItem) error {
	if err := copyDeadline(admission); err != nil {
		return err
	}
	session, err := s.openSession(ctx, admission.DestinationScopeID, true)
	if err != nil {
		return err
	}
	defer func() { _ = session.tx.Rollback(ctx) }()
	done, err := session.copyCommitted(ctx, admission, item)
	if err != nil || done {
		return err
	}
	if err = session.copyActive(ctx, admission); err != nil {
		return err
	}
	sourceSession, err := session.inScope(ctx, admission.ScopeID)
	if err != nil {
		return err
	}
	if _, err = sourceSession.copySource(ctx, item, true); err != nil {
		return err
	}
	if item.Kind == "file" && !session.allowBlobFiles {
		if item.ObjectKey != nil {
			return apperr.New(apperr.Invalid, "BLOB_FILES_DISABLED", "destination scope does not allow blob files")
		}
		var content []byte
		if err = session.tx.QueryRow(ctx, `SELECT inline_bytes FROM files WHERE node_id=$1`, item.Source).Scan(&content); err != nil {
			return databaseError(err)
		}
		if err = session.validateInlineText(content); err != nil {
			return err
		}
	}
	var key *string
	if item.ObjectKey != nil {
		if s.Storage == nil {
			return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "storage unavailable")
		}
		value := fmt.Sprintf("objects/%s/%s", session.filesystemID, item.Destination)
		key = &value
		changed, err := session.tx.Exec(ctx, `INSERT INTO object_deletions(object_key,filesystem_id,open_writes) VALUES($1,$2,1)
 ON CONFLICT(object_key) DO UPDATE SET open_writes=object_deletions.open_writes+1,eligible_at=now()+interval '15 minutes'
 WHERE object_deletions.state='pending'`, key, session.filesystemID)
		if err != nil {
			return databaseError(err)
		}
		if changed.RowsAffected() != 1 {
			return apperr.New(apperr.Conflict, "COPY_CANDIDATE_CLOSED", "copy candidate cleanup already started")
		}
		if err = session.tx.Commit(ctx); err != nil {
			return databaseError(err)
		}
		if err = s.Storage.Copy(ctx, *item.ObjectKey, *key); err != nil {
			return storageError(ctx, err)
		}
		next, err := s.lifecycleSession(ctx, admission.DestinationScopeID)
		if err != nil {
			return err
		}
		session = next
		if _, err = session.tx.Exec(ctx, `UPDATE object_deletions SET open_writes=open_writes-1 WHERE object_key=$1 AND open_writes>0`, key); err != nil {
			return databaseError(err)
		}
		done, err = session.validateCopyCandidate(ctx, admission, item, *key)
		if err != nil {
			if commitErr := session.tx.Commit(ctx); commitErr != nil {
				return databaseError(commitErr)
			}
			return err
		}
		if done {
			if err = session.releaseCopyCandidate(ctx, *key); err != nil {
				return err
			}
			return databaseError(session.tx.Commit(ctx))
		}
	}
	if _, err = session.tx.Exec(ctx, `SAVEPOINT copy_publication`); err != nil {
		return databaseError(err)
	}
	published := func() error {
		if err := session.addNodes(ctx, 1); err != nil {
			return err
		}
		if err := session.usage(ctx, item.Size); err != nil {
			return err
		}
		if _, err := session.tx.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,$4,$5,$6)`, item.Destination, session.scopeID, item.Parent, item.Name, item.Kind, item.Size); err != nil {
			return databaseError(err)
		}
		if item.Kind == "file" {
			if _, err := session.tx.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes,object_key,media_type,title,description,semantic_type,context)
 SELECT $1,storage_kind,inline_bytes,$3,media_type,title,description,semantic_type,context FROM files WHERE node_id=$2`, item.Destination, item.Source, key); err != nil {
				return databaseError(err)
			}
		}
		return session.bump(ctx, item.Parent)
	}()
	if published != nil {
		if _, err = session.tx.Exec(ctx, `ROLLBACK TO SAVEPOINT copy_publication`); err != nil {
			return databaseError(err)
		}
	}
	if key != nil {
		if err = session.releaseCopyCandidate(ctx, *key); err != nil {
			return err
		}
	}
	if err = session.tx.Commit(ctx); err != nil {
		return databaseError(err)
	}
	return published
}

type CopyFrame struct {
	SourceScopeID uuid.UUID
	Item          CopyItem  `json:"item"`
	After         uuid.UUID `json:"after"`
	Revision      int64     `json:"revision,string"`
}

func (s *session) copyFrame(ctx context.Context, frame CopyFrame) (Node, error) {
	sourceSession, err := s.inScope(ctx, frame.SourceScopeID)
	if err != nil {
		return Node{}, err
	}
	if _, err := sourceSession.copySource(ctx, frame.Item, false); err != nil {
		return Node{}, err
	}
	node, err := s.copyNode(ctx, frame.Item.Destination)
	if err != nil {
		return Node{}, err
	}
	if node.ParentID == nil || *node.ParentID != frame.Item.Parent || node.Name != frame.Item.Name || node.Kind != frame.Item.Kind || node.Revision != frame.Revision {
		return Node{}, apperr.New(apperr.Conflict, "DESTINATION_CHANGED", "copy destination changed")
	}
	return node, nil
}
func (s *Store) nextCopyItem(ctx context.Context, admission CopyAdmission, frame CopyFrame) (*CopyItem, error) {
	if err := copyDeadline(admission); err != nil {
		return nil, err
	}
	session, err := s.openSession(ctx, admission.DestinationScopeID, false)
	if err != nil {
		return nil, err
	}
	defer session.tx.Rollback(ctx)
	parent, err := session.copyFrame(ctx, frame)
	if err != nil {
		return nil, err
	}
	var child uuid.UUID
	err = session.tx.QueryRow(ctx, `SELECT id FROM nodes WHERE scope_id=$1 AND parent_id=$2 AND id>$3 AND id<=$4 ORDER BY id LIMIT 1`, admission.ScopeID, frame.Item.Source, frame.After, frame.Item.Upper).Scan(&child)
	if err == pgx.ErrNoRows {
		return nil, nil
	}
	if err != nil {
		return nil, databaseError(err)
	}
	if frame.Item.Depth >= maxDepth {
		return nil, apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "tree depth limit exceeded")
	}
	sourceSession, err := session.inScope(ctx, admission.ScopeID)
	if err != nil {
		return nil, err
	}
	node, err := sourceSession.copyNode(ctx, child)
	if err != nil {
		return nil, err
	}
	item, err := sourceSession.selectCopy(ctx, admission.ID, node, parent, node.Name, frame.Item.Derived || frame.Item.Kind == "file", frame.Item.Depth+1)
	return &item, err
}
func (s *Store) CloseCopyAdmission(ctx context.Context, admission CopyAdmission) error {
	session, err := s.lifecycleSession(ctx, admission.DestinationScopeID)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	_, err = session.tx.Exec(ctx, `UPDATE idempotency_keys SET expires_at=now()+interval '24 hours'
 WHERE operation='copy-node' AND result->>'id'=$1 AND expires_at IS NULL`, admission.ID.String())
	if err != nil {
		return databaseError(err)
	}
	return databaseError(session.tx.Commit(ctx))
}

// finishCopyFile records processing intent after the copied file subtree completes.
func (s *Store) finishCopyFile(ctx context.Context, admission CopyAdmission, frame CopyFrame) error {
	if frame.Item.Kind != "file" || frame.Item.Derived {
		return nil
	}
	session, err := s.openSession(ctx, admission.DestinationScopeID, true)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.copyFrame(ctx, frame)
	if err != nil {
		return err
	}
	var initialized bool
	if err = session.tx.QueryRow(ctx, `SELECT desired_generation>0 FROM files WHERE node_id=$1`, node.ID).Scan(&initialized); err != nil {
		return databaseError(err)
	}
	if !initialized {
		if err = session.recordIntent(ctx, node); err != nil {
			return err
		}
		if format, _ := processingFormat(node.Name); format != "" {
			_, err = session.tx.Exec(ctx, `UPDATE files SET publication_status='parsed' WHERE node_id=$1 AND EXISTS(SELECT 1 FROM nodes WHERE parent_id=$1)`, node.ID)
			if err != nil {
				return databaseError(err)
			}
		}
	}
	return databaseError(session.tx.Commit(ctx))
}

func (s *session) inScope(ctx context.Context, id uuid.UUID) (*session, error) {
	other := *s
	other.scopeID = id
	if err := s.tx.QueryRow(ctx, `SELECT root_id,allow_blob_files,allow_indexing FROM scopes WHERE id=$1 AND filesystem_id=$2 AND state='active'`, id, s.filesystemID).Scan(&other.root, &other.allowBlobFiles, &other.allowIndexing); err != nil {
		return nil, databaseError(err)
	}
	return &other, nil
}

// CopyTreeData uses only local traversal state; partial writes are retained on error.
func (s *Store) CopyTreeData(ctx context.Context, in CopyAdmission) (err error) {
	defer func() {
		cleanup, cancel := context.WithTimeout(context.WithoutCancel(ctx), 30*time.Second)
		defer cancel()
		closeErr := s.CloseCopyAdmission(cleanup, in)
		if err == nil {
			err = closeErr
		}
	}()
	var nodes, bytes int64
	var visit func(CopyItem) error
	visit = func(item CopyItem) error {
		nodes++
		bytes += item.Size
		if nodes > in.MaxNodes || bytes > in.MaxBytes {
			return apperr.New(apperr.Limit, "RESOURCE_LIMIT", "copy bound exceeded")
		}
		if err := s.commitCopyItem(ctx, in, item); err != nil {
			return err
		}
		frame := CopyFrame{SourceScopeID: in.ScopeID, Item: item, Revision: 1}
		for {
			child, err := s.nextCopyItem(ctx, in, frame)
			if err != nil {
				return err
			}
			if child == nil {
				break
			}
			if err = visit(*child); err != nil {
				return err
			}
			frame.After = child.Source
			frame.Revision++
		}
		return s.finishCopyFile(ctx, in, frame)
	}
	return visit(in.Root)
}
