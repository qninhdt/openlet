package filesystem

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/identity"
)

type ScopePage struct {
	Items      []Scope
	NextCursor *string
}

// ListScopes returns storage candidates; Workspace filters current effective rights.
func (s *Store) ListScopes(ctx context.Context, fs uuid.UUID, cursor *string, limit *int32) (ScopePage, error) {
	principal, ok := identity.FromContext(ctx)
	if !ok || principal.Service != "workspace" || principal.Gateway || principal.ActorID != uuid.Nil || principal.ActorKind != "" {
		return ScopePage{}, apperr.New(apperr.Forbidden, "FORBIDDEN", "actor-free workspace service required")
	}
	if fs == uuid.Nil {
		return ScopePage{}, apperr.New(apperr.Invalid, "VALIDATION", "filesystem identity required")
	}
	cursorScope := "scopes/" + fs.String()
	if cursor != nil && len(*cursor) > 512 {
		return ScopePage{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid scope cursor")
	}
	after, count, err := page(cursorScope, cursor, limit)
	if err != nil {
		return ScopePage{}, err
	}
	tx, err := s.DB.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return ScopePage{}, databaseError(err)
	}
	defer tx.Rollback(ctx)
	var state string
	if err = tx.QueryRow(ctx, `SELECT state FROM filesystems WHERE id=$1`, fs).Scan(&state); err != nil {
		return ScopePage{}, databaseError(err)
	}
	if state != "active" {
		return ScopePage{}, apperr.New(apperr.Missing, "NOT_FOUND", "resource not found")
	}
	rows, err := tx.Query(ctx, `SELECT s.id,s.filesystem_id,s.root_id,s.state,s.allow_blob_files,s.allow_indexing
 FROM scopes s JOIN nodes n ON n.id=s.root_id AND n.scope_id=s.id AND n.parent_id IS NULL AND n.kind='directory'
 WHERE s.filesystem_id=$1 AND s.state='active' AND s.id>$2 ORDER BY s.id LIMIT $3`, fs, after, count+1)
	if err != nil {
		return ScopePage{}, databaseError(err)
	}
	defer rows.Close()
	result := ScopePage{Items: []Scope{}}
	for rows.Next() {
		var scope Scope
		if err = rows.Scan(&scope.ID, &scope.FilesystemID, &scope.RootID, &scope.State, &scope.AllowBlobFiles, &scope.AllowIndexing); err != nil {
			return ScopePage{}, databaseError(err)
		}
		result.Items = append(result.Items, scope)
	}
	if err = rows.Err(); err != nil {
		return ScopePage{}, databaseError(err)
	}
	if len(result.Items) > int(count) {
		result.Items = result.Items[:count]
		next := cursorScope + "|" + result.Items[count-1].ID.String()
		result.NextCursor = &next
	}
	return result, nil
}
