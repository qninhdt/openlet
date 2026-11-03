package filesystem

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type TrashEntry struct {
	ID        uuid.UUID  `json:"id"`
	NodeID    uuid.UUID  `json:"node_id"`
	ParentID  *uuid.UUID `json:"parent_id"`
	Name      string     `json:"name"`
	ActorID   uuid.UUID  `json:"actor_id"`
	Status    string     `json:"status"`
	CreatedAt time.Time  `json:"created_at"`
}

func (entry *TrashEntry) fields() []any {
	return []any{&entry.ID, &entry.NodeID, &entry.ParentID, &entry.Name, &entry.ActorID, &entry.Status, &entry.CreatedAt}
}

const trashColumns = `id,node_id,original_parent_id,original_name,actor_id,state,created_at`

func (s *session) queueObject(ctx context.Context, id uuid.UUID) error {
	_, err := s.tx.Exec(ctx, `INSERT INTO object_deletions(object_key,bucket_id)
 SELECT object_key,$2 FROM files WHERE node_id=$1 AND object_key IS NOT NULL ON CONFLICT DO NOTHING`, id, s.bucket)
	return databaseError(err)
}

func (s *session) trashEntry(ctx context.Context, id uuid.UUID, lock bool) (TrashEntry, error) {
	query := `SELECT ` + trashColumns + ` FROM trash_entries WHERE filesystem_id=$1 AND id=$2`
	if lock {
		query += ` FOR UPDATE`
	}
	var entry TrashEntry
	err := s.tx.QueryRow(ctx, query, s.fs, id).Scan(entry.fields()...)
	return entry, databaseError(err)
}

func (s *Store) GetTrash(ctx context.Context, fs, id uuid.UUID) (TrashEntry, error) {
	if _, err := s.authorize(ctx, fs, "filesystem", authz.TrashRead); err != nil {
		return TrashEntry{}, err
	}
	session, err := s.openSession(ctx, fs, false)
	if err != nil {
		return TrashEntry{}, err
	}
	defer session.tx.Rollback(ctx)
	return session.trashEntry(ctx, id, false)
}

type TrashPage struct {
	Items      []TrashEntry `json:"items"`
	NextCursor *string      `json:"next_cursor"`
}

func (s *Store) ListTrash(ctx context.Context, fs uuid.UUID, cursor *string, limit *int32) (TrashPage, error) {
	if _, err := s.authorize(ctx, fs, "filesystem", authz.TrashRead); err != nil {
		return TrashPage{}, err
	}
	scope := "trash/" + fs.String()
	after, count, err := page(scope, cursor, limit)
	if err != nil {
		return TrashPage{}, err
	}
	session, err := s.openSession(ctx, fs, false)
	if err != nil {
		return TrashPage{}, err
	}
	defer session.tx.Rollback(ctx)
	rows, err := session.tx.Query(ctx, `SELECT `+trashColumns+` FROM trash_entries WHERE filesystem_id=$1 AND id>$2 ORDER BY id LIMIT $3`, fs, after, count+1)
	if err != nil {
		return TrashPage{}, databaseError(err)
	}
	defer rows.Close()
	result := TrashPage{Items: []TrashEntry{}}
	for rows.Next() {
		var entry TrashEntry
		if err = rows.Scan(entry.fields()...); err != nil {
			return TrashPage{}, databaseError(err)
		}
		result.Items = append(result.Items, entry)
	}
	if err = rows.Err(); err != nil {
		return TrashPage{}, databaseError(err)
	}
	if len(result.Items) > int(count) {
		result.Items = result.Items[:count]
		next := scope + "|" + result.Items[count-1].ID.String()
		result.NextCursor = &next
	}
	return result, nil
}

func (s *Store) TrashNode(ctx context.Context, fs uuid.UUID, mounts []Mount, locator Locator, revision *int64) (TrashEntry, error) {
	actor, err := s.authorize(ctx, fs, "filesystem", authz.NodeTrash)
	if err != nil {
		return TrashEntry{}, err
	}
	session, err := s.openSession(ctx, fs, true)
	if err != nil {
		return TrashEntry{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, mounts, locator)
	if err != nil {
		return TrashEntry{}, err
	}
	if err = guard(locator, node.ID, false); err != nil {
		return TrashEntry{}, err
	}
	if err = node.writable(); err != nil {
		return TrashEntry{}, err
	}
	if err = node.revision(revision); err != nil {
		return TrashEntry{}, err
	}
	if node.ID == session.root {
		return TrashEntry{}, apperr.New(apperr.Conflict, "ROOT_IMMUTABLE", "root is immutable")
	}
	if err = session.fenceTrashed(ctx, node.ID); err != nil {
		return TrashEntry{}, err
	}
	id := uuid.Must(uuid.NewV7())
	_, err = session.tx.Exec(ctx, `INSERT INTO trash_entries(id,filesystem_id,node_id,original_parent_id,original_name,actor_id) VALUES($1,$2,$3,$4,$5,$6)`, id, fs, node.ID, node.ParentID, node.Name, actor)
	if err != nil {
		return TrashEntry{}, databaseError(err)
	}
	_, err = session.tx.Exec(ctx, `UPDATE nodes SET parent_id=NULL WHERE id=$1`, node.ID)
	if err != nil {
		return TrashEntry{}, databaseError(err)
	}
	if err = session.bump(ctx, node.ID, *node.ParentID); err != nil {
		return TrashEntry{}, err
	}
	entry, err := session.trashEntry(ctx, id, false)
	if err != nil {
		return TrashEntry{}, err
	}
	return entry, databaseError(session.tx.Commit(ctx))
}

func (s *Store) RestoreTrash(ctx context.Context, fs, id uuid.UUID) (Node, error) {
	if _, err := s.authorize(ctx, fs, "filesystem", authz.TrashRestore); err != nil {
		return Node{}, err
	}
	session, err := s.openSession(ctx, fs, true)
	if err != nil {
		return Node{}, err
	}
	defer session.tx.Rollback(ctx)
	entry, err := session.trashEntry(ctx, id, true)
	if err != nil {
		return Node{}, err
	}
	if entry.Status != "trashed" {
		return Node{}, apperr.New(apperr.Conflict, "TRASH_PURGING", "trash entry is being purged")
	}
	if entry.ParentID == nil {
		return Node{}, apperr.New(apperr.Missing, "NOT_FOUND", "original parent not found")
	}
	parent, err := session.resolveOne(ctx, []Mount{{Path: "/", FilesystemID: fs}}, Locator{NodeID: entry.ParentID})
	if err != nil {
		return Node{}, err
	}
	if err = parent.writable(); err != nil {
		return Node{}, err
	}
	if err = parent.directory(); err != nil {
		return Node{}, err
	}
	if err = session.name(parent.ID, entry.Name); err != nil {
		return Node{}, err
	}
	if err = session.validateMove(ctx, entry.NodeID, parent.ID); err != nil {
		return Node{}, err
	}
	_, err = session.tx.Exec(ctx, `UPDATE nodes SET parent_id=$2,name=$3 WHERE id=$1`, entry.NodeID, parent.ID, entry.Name)
	if err != nil {
		return Node{}, databaseError(err)
	}
	_, err = session.tx.Exec(ctx, `DELETE FROM trash_entries WHERE id=$1`, id)
	if err != nil {
		return Node{}, databaseError(err)
	}
	if err = session.bump(ctx, entry.NodeID, parent.ID); err != nil {
		return Node{}, err
	}
	node, err := session.fetch(ctx, entry.NodeID)
	if err != nil {
		return Node{}, err
	}
	return node, databaseError(session.tx.Commit(ctx))
}
