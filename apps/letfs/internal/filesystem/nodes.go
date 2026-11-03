package filesystem

import (
	"context"
	"errors"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type Node struct {
	ID           uuid.UUID  `json:"id"`
	FilesystemID uuid.UUID  `json:"filesystem_id"`
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

const nodeColumns = `n.id,n.filesystem_id,n.parent_id,n.name,n.kind,n.revision,n.size_bytes,n.created_at,n.updated_at,
 f.media_type,f.title,f.description,f.semantic_type,f.context`

func (n *Node) fields() []any {
	return []any{&n.ID, &n.FilesystemID, &n.ParentID, &n.Name, &n.Kind, &n.Revision, &n.SizeBytes, &n.CreatedAt, &n.UpdatedAt,
		&n.MediaType, &n.Title, &n.Description, &n.SemanticType, &n.Context, &n.readonly}
}

func (n Node) writable() error {
	if n.readonly {
		return rpc.Fault(codes.PermissionDenied, "ARTIFACT_READ_ONLY", "generated artifacts are read only")
	}
	return nil
}

func (n Node) directory() error {
	if n.Kind != "directory" {
		return rpc.Fault(codes.Aborted, "NOT_DIRECTORY", "directory required")
	}
	return nil
}

func (n Node) revision(expected *int64) error {
	if expected == nil {
		return rpc.Fault(codes.FailedPrecondition, "PRECONDITION_REQUIRED", "revision required")
	}
	if *expected <= 0 {
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "positive revision required")
	}
	if n.Revision != *expected {
		return rpc.Fault(codes.FailedPrecondition, "REVISION_MISMATCH", "revision mismatch")
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
	if _, ok := status.FromError(err); ok {
		return err
	}
	if errors.Is(err, pgx.ErrNoRows) {
		return rpc.Fault(codes.NotFound, "NOT_FOUND", "resource not found")
	}
	var pg *pgconn.PgError
	if errors.As(err, &pg) && pg.Code == "23505" {
		return rpc.Fault(codes.AlreadyExists, "NAME_CONFLICT", "name already exists")
	}
	return rpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "database unavailable")
}

type session struct {
	tx               pgx.Tx
	maxNodes         int64
	fs, bucket, root uuid.UUID
}

func (s *Store) openSession(ctx context.Context, fs uuid.UUID, write bool) (_ *session, err error) {
	return s.openSessionState(ctx, fs, write, false)
}

func (s *Store) lifecycleSession(ctx context.Context, fs uuid.UUID) (*session, error) {
	return s.openSessionState(ctx, fs, true, true)
}

func (s *Store) openSessionState(ctx context.Context, fs uuid.UUID, write, allowInactive bool) (_ *session, err error) {
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
	result := &session{maxNodes: s.MaxNodes, tx: tx, fs: fs}
	if err = tx.QueryRow(ctx, `SELECT bucket_id FROM filesystems WHERE id=$1`, fs).Scan(&result.bucket); err != nil {
		return nil, databaseError(err)
	}
	bucketSQL := `SELECT state FROM quota_buckets WHERE id=$1`
	fsSQL := `SELECT root_id,state FROM filesystems WHERE id=$1`
	if write {
		bucketSQL += ` FOR UPDATE`
		fsSQL += ` FOR UPDATE`
	}
	var state string
	if err = tx.QueryRow(ctx, bucketSQL, result.bucket).Scan(&state); err != nil {
		return nil, databaseError(err)
	}
	if state != "active" && !allowInactive {
		return nil, rpc.Fault(codes.Aborted, "BUCKET_FROZEN", "bucket is frozen")
	}
	var root *uuid.UUID
	if err = tx.QueryRow(ctx, fsSQL, fs).Scan(&root, &state); err != nil {
		return nil, databaseError(err)
	}
	if !allowInactive && (state != "active" || root == nil) {
		return nil, rpc.Fault(codes.NotFound, "NOT_FOUND", "resource not found")
	}
	if root != nil {
		result.root = *root
	}
	return result, nil
}

func (s *Store) GetFilesystem(ctx context.Context, fs uuid.UUID) (Filesystem, error) {
	if _, err := s.authorize(ctx, fs, "filesystem", authz.NodeRead); err != nil {
		return Filesystem{}, err
	}
	session, err := s.openSession(ctx, fs, false)
	if err != nil {
		return Filesystem{}, err
	}
	defer session.tx.Rollback(ctx)
	return Filesystem{ID: fs, BucketID: session.bucket, RootID: &session.root, State: "active"}, nil
}

func (s *Store) GetBucketUsage(ctx context.Context, id uuid.UUID) (Bucket, error) {
	if _, err := s.authorize(ctx, id, "quota_bucket", authz.BucketRead); err != nil {
		return Bucket{}, err
	}
	var result Bucket
	err := s.DB.QueryRow(ctx, `SELECT id,limit_bytes,used_bytes,state FROM quota_buckets WHERE id=$1`, id).
		Scan(&result.ID, &result.LimitBytes, &result.UsedBytes, &result.State)
	return result, databaseError(err)
}

func (s *Store) GetNode(ctx context.Context, fs uuid.UUID, mounts []Mount, locator Locator) (Node, error) {
	return s.readNode(ctx, fs, mounts, locator, authz.NodeRead)
}

func (s *Store) ResolveNode(ctx context.Context, fs uuid.UUID, mounts []Mount, locator Locator) (Node, error) {
	return s.readNode(ctx, fs, mounts, locator, authz.NodeResolve)
}

func (s *Store) readNode(ctx context.Context, fs uuid.UUID, mounts []Mount, locator Locator, action authz.Action) (Node, error) {
	if _, err := s.authorize(ctx, fs, "filesystem", action); err != nil {
		return Node{}, err
	}
	session, err := s.openSession(ctx, fs, false)
	if err != nil {
		return Node{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, mounts, locator)
	if err == nil && locator.ExpectedNodeID != nil && *locator.ExpectedNodeID != node.ID {
		err = rpc.Fault(codes.Aborted, "TARGET_MISMATCH", "target mismatch")
	}
	return node, err
}

func (s *Store) BatchStat(ctx context.Context, fs uuid.UUID, mounts []Mount, locators []Locator) ([]Node, error) {
	if _, err := s.authorize(ctx, fs, "filesystem", authz.NodeRead); err != nil {
		return nil, err
	}
	session, err := s.openSession(ctx, fs, false)
	if err != nil {
		return nil, err
	}
	defer session.tx.Rollback(ctx)
	return session.resolve(ctx, mounts, locators)
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
	invalid := rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid page limit or cursor")
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

func (s *Store) ListNodes(ctx context.Context, fs uuid.UUID, mounts []Mount, parent Locator, cursor *string, limit *int32) (NodePage, error) {
	if _, err := s.authorize(ctx, fs, "filesystem", authz.NodeList); err != nil {
		return NodePage{}, err
	}
	session, err := s.openSession(ctx, fs, false)
	if err != nil {
		return NodePage{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, mounts, parent)
	if err != nil {
		return NodePage{}, err
	}
	if parent.ExpectedNodeID != nil && *parent.ExpectedNodeID != node.ID {
		return NodePage{}, rpc.Fault(codes.Aborted, "TARGET_MISMATCH", "target mismatch")
	}
	scope := "list/" + fs.String() + "/" + node.ID.String()
	after, count, err := page(scope, cursor, limit)
	if err != nil {
		return NodePage{}, err
	}
	rows, err := session.tx.Query(ctx, `SELECT `+strings.Replace(nodeColumns, "f.context", "NULL::text", 1)+`,false
 FROM nodes n LEFT JOIN files f ON f.node_id=n.id WHERE n.filesystem_id=$1 AND n.parent_id=$2 AND n.id>$3 ORDER BY n.id LIMIT $4`, fs, node.ID, after, count+1)
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
