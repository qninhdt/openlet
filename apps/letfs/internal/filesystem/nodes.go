package filesystem

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type Node struct {
	ID           uuid.UUID  `json:"id"`
	ScopeID      uuid.UUID  `json:"scope_id"`
	ParentID     *uuid.UUID `json:"parent_id"`
	Name         string     `json:"name"`
	Kind         string     `json:"kind"`
	Revision     int64      `json:"revision,string"`
	SizeBytes    int64      `json:"size_bytes,string"`
	CreatedAt    time.Time  `json:"created_at"`
	UpdatedAt    time.Time  `json:"updated_at"`
	MediaType    *string    `json:"media_type,omitempty"`
	Title        *string    `json:"title,omitempty"`
	Description  *string    `json:"description,omitempty"`
	SemanticType *string    `json:"semantic_type,omitempty"`
	Context      *string    `json:"context,omitempty"`
	readonly     bool
}

const nodeColumns = `n.id,n.scope_id,n.parent_id,n.name,n.kind,n.revision,n.size_bytes,n.created_at,n.updated_at,
 f.media_type,f.title,f.description,f.semantic_type,f.context`

func (n *Node) fields() []any {
	return []any{&n.ID, &n.ScopeID, &n.ParentID, &n.Name, &n.Kind, &n.Revision, &n.SizeBytes, &n.CreatedAt, &n.UpdatedAt,
		&n.MediaType, &n.Title, &n.Description, &n.SemanticType, &n.Context, &n.readonly}
}

func (n Node) writable() error {
	if n.readonly {
		return apperr.New(apperr.Forbidden, "ARTIFACT_READ_ONLY", "generated artifacts are read only")
	}
	return nil
}

func (n Node) directory() error {
	if n.Kind != "directory" {
		return apperr.New(apperr.Conflict, "NOT_DIRECTORY", "directory required")
	}
	return nil
}

func (n Node) revision(expected *int64) error {
	if expected == nil {
		return apperr.New(apperr.Precondition, "PRECONDITION_REQUIRED", "revision required")
	}
	if *expected <= 0 {
		return apperr.New(apperr.Invalid, "VALIDATION", "positive revision required")
	}
	if n.Revision != *expected {
		return apperr.New(apperr.Precondition, "REVISION_MISMATCH", "revision mismatch")
	}
	return nil
}

func databaseError(err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	if _, ok := apperr.As(err); ok {
		return err
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return apperr.New(apperr.Missing, "NOT_FOUND", "resource not found")
	}
	var pg *pgconn.PgError
	if errors.As(err, &pg) && pg.Code == "23505" {
		return apperr.New(apperr.Exists, "NAME_CONFLICT", "name already exists")
	}
	return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "database unavailable")
}

type session struct {
	tx                            pgx.Tx
	maxNodes                      int64
	scopeID, filesystemID, root   uuid.UUID
	allowBlobFiles, allowIndexing bool
}

func (s *Store) openSession(ctx context.Context, scopeID uuid.UUID, write bool) (_ *session, err error) {
	return s.openSessionState(ctx, scopeID, write, false)
}

func (s *Store) lifecycleSession(ctx context.Context, scopeID uuid.UUID) (*session, error) {
	return s.openSessionState(ctx, scopeID, true, true)
}

func (s *Store) openSessionState(ctx context.Context, scopeID uuid.UUID, write, allowInactive bool) (_ *session, err error) {
	options := pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}
	if write {
		options = pgx.TxOptions{}
	}
	tx, err := s.DB.BeginTx(ctx, options)
	if err != nil {
		return nil, databaseError(err)
	}
	defer func() {
		if err != nil {
			_ = tx.Rollback(ctx)
		}
	}()
	result := &session{maxNodes: s.MaxNodes, tx: tx, scopeID: scopeID}
	if err = tx.QueryRow(ctx, `SELECT filesystem_id FROM scopes WHERE id=$1`, scopeID).Scan(&result.filesystemID); err != nil {
		return nil, databaseError(err)
	}
	fsSQL := `SELECT state FROM filesystems WHERE id=$1`
	scopeSQL := `SELECT root_id,state,allow_blob_files,allow_indexing FROM scopes WHERE id=$1 AND filesystem_id=$2`
	if write {
		fsSQL += ` FOR UPDATE`
		scopeSQL += ` FOR UPDATE`
	}
	var fsState, scopeState string
	if err = tx.QueryRow(ctx, fsSQL, result.filesystemID).Scan(&fsState); err != nil {
		return nil, databaseError(err)
	}
	var root *uuid.UUID
	if err = tx.QueryRow(ctx, scopeSQL, scopeID, result.filesystemID).Scan(&root, &scopeState, &result.allowBlobFiles, &result.allowIndexing); err != nil {
		return nil, databaseError(err)
	}
	if !allowInactive && (fsState != "active" || scopeState != "active" || root == nil) {
		return nil, apperr.New(apperr.Missing, "NOT_FOUND", "resource not found")
	}
	if root != nil {
		result.root = *root
	}
	return result, nil
}

// ValidateScope binds externally supplied filesystem and scope identities before any operation.
func (s *Store) ValidateScope(ctx context.Context, fs, scope uuid.UUID) error {
	var found bool
	err := s.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM scopes WHERE id=$1 AND filesystem_id=$2 AND state<>'deleted')`, scope, fs).Scan(&found)
	if err != nil {
		return databaseError(err)
	}
	if !found {
		return apperr.New(apperr.Missing, "NOT_FOUND", "resource not found")
	}
	return nil
}

func (s *Store) GetFilesystem(ctx context.Context, id uuid.UUID) (Filesystem, error) {
	if _, err := s.authorize(ctx, id, "filesystem", authz.FilesystemRead); err != nil {
		return Filesystem{}, err
	}
	var value Filesystem
	err := s.DB.QueryRow(ctx, `SELECT id,limit_bytes,used_bytes,node_count,state FROM filesystems WHERE id=$1 AND state<>'deleted'`, id).Scan(&value.ID, &value.LimitBytes, &value.UsedBytes, &value.NodeCount, &value.State)
	return value, databaseError(err)
}

func (s *Store) GetNode(ctx context.Context, scopeID uuid.UUID, locator Locator) (Node, error) {
	return s.readNode(ctx, scopeID, locator, authz.ScopeReadMetadata)
}

func (s *Store) ResolveNode(ctx context.Context, scopeID uuid.UUID, locator Locator) (Node, error) {
	return s.readNode(ctx, scopeID, locator, authz.ScopeReadMetadata)
}

func (s *Store) readNode(ctx context.Context, scopeID uuid.UUID, locator Locator, action authz.Action) (Node, error) {
	if _, err := s.authorize(ctx, scopeID, "scope", action); err != nil {
		return Node{}, err
	}
	session, err := s.openSession(ctx, scopeID, false)
	if err != nil {
		return Node{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, locator)
	if err == nil && locator.ExpectedNodeID != nil && *locator.ExpectedNodeID != node.ID {
		err = apperr.New(apperr.Conflict, "TARGET_MISMATCH", "target mismatch")
	}
	node.Context = nil
	return node, err
}

func (s *Store) BatchStat(ctx context.Context, scopeID uuid.UUID, locators []Locator) ([]Node, error) {
	if _, err := s.authorize(ctx, scopeID, "scope", authz.ScopeReadMetadata); err != nil {
		return nil, err
	}
	session, err := s.openSession(ctx, scopeID, false)
	if err != nil {
		return nil, err
	}
	defer session.tx.Rollback(ctx)
	nodes, err := session.resolve(ctx, locators)
	for i := range nodes {
		nodes[i].Context = nil
	}
	return nodes, err
}

type NodePage struct {
	Items      []Node  `json:"items"`
	NextCursor *string `json:"next_cursor"`
}

func page(scope string, cursor *string, limit *int32) (uuid.UUID, int32, error) {
	count := int32(50)
	if limit != nil {
		count = *limit
	}
	invalid := apperr.New(apperr.Invalid, "VALIDATION", "invalid page limit or cursor")
	if count < 1 || count > 100 {
		return uuid.Nil, 0, invalid
	}
	after := uuid.Nil
	if cursor != nil {
		prefix, value, ok := strings.Cut(*cursor, "|")
		var err error
		after, err = uuid.Parse(value)
		if !ok || prefix != scope || err != nil {
			return uuid.Nil, 0, invalid
		}
	}
	return after, count, nil
}

func (s *Store) ListNodes(ctx context.Context, scopeID uuid.UUID, parent Locator, cursor *string, limit *int32) (NodePage, error) {
	if _, err := s.authorize(ctx, scopeID, "scope", authz.ScopeReadMetadata); err != nil {
		return NodePage{}, err
	}
	session, err := s.openSession(ctx, scopeID, false)
	if err != nil {
		return NodePage{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, parent)
	if err != nil {
		return NodePage{}, err
	}
	if parent.ExpectedNodeID != nil && *parent.ExpectedNodeID != node.ID {
		return NodePage{}, apperr.New(apperr.Conflict, "TARGET_MISMATCH", "target mismatch")
	}
	scope := "list/" + scopeID.String() + "/" + node.ID.String()
	after, count, err := page(scope, cursor, limit)
	if err != nil {
		return NodePage{}, err
	}
	rows, err := session.tx.Query(ctx, `SELECT `+strings.Replace(nodeColumns, "f.context", "NULL::text", 1)+`,false
 FROM nodes n LEFT JOIN files f ON f.node_id=n.id WHERE n.scope_id=$1 AND n.parent_id=$2 AND n.id>$3 ORDER BY n.id LIMIT $4`, scopeID, node.ID, after, count+1)
	if err != nil {
		return NodePage{}, databaseError(err)
	}
	defer rows.Close()
	result := NodePage{Items: []Node{}}
	for rows.Next() {
		var child Node
		if err = rows.Scan(child.fields()...); err != nil {
			return NodePage{}, databaseError(err)
		}
		result.Items = append(result.Items, child)
	}
	if err = rows.Err(); err != nil {
		return NodePage{}, databaseError(err)
	}
	if len(result.Items) > int(count) {
		result.Items = result.Items[:count]
		next := scope + "|" + result.Items[count-1].ID.String()
		result.NextCursor = &next
	}
	return result, nil
}
