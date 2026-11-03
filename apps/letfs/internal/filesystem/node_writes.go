package filesystem

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
)

type InlineFile struct {
	Content   []byte `json:"content"`
	MediaType string `json:"media_type"`
}

type CreateNode struct {
	Parent Locator     `json:"parent"`
	Name   string      `json:"name"`
	File   *InlineFile `json:"file,omitempty"`
}

func mediaType(value string) error {
	invalid := rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid media type")
	if !utf8.ValidString(value) || len(value) > 200 {
		return invalid
	}
	for _, b := range []byte(value) {
		if b < 32 && b != '\t' || b == 127 {
			return invalid
		}
	}
	typeName, _, _ := strings.Cut(value, ";")
	major, minor, ok := strings.Cut(strings.TrimSpace(typeName), "/")
	if !ok {
		return invalid
	}
	for _, token := range []string{major, minor} {
		if token == "" {
			return invalid
		}
		for _, b := range []byte(token) {
			if !(b >= 'a' && b <= 'z' || b >= 'A' && b <= 'Z' || b >= '0' && b <= '9' || strings.ContainsRune("!#$&^_.+-", rune(b))) {
				return invalid
			}
		}
	}
	return nil
}

func (s *Store) inlineSize(content []byte) error {
	if int64(len(content)) > min(s.InlineLimit, s.MaxFileBytes) {
		return rpc.Fault(codes.ResourceExhausted, "REQUEST_LIMIT", "inline content exceeds limit")
	}
	return nil
}

func (s *session) name(parent uuid.UUID, name string) error {
	if err := ValidateName(name); err != nil {
		return err
	}
	if _, alias := nodeAlias(name); parent == s.root && alias {
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "root UUID alias names are reserved")
	}
	return nil
}

func (s *session) usage(ctx context.Context, delta int64) error {
	changed, err := s.tx.Exec(ctx, `UPDATE quota_buckets SET used_bytes=used_bytes+$2
 WHERE id=$1 AND used_bytes+$2>=0 AND ($2<=0 OR used_bytes<=limit_bytes-$2)
 AND (state='active' OR ($2<=0 AND state='frozen'))`, s.bucket, delta)
	if err != nil {
		return databaseError(err)
	}
	if changed.RowsAffected() != 1 {
		return rpc.Fault(codes.Aborted, "QUOTA_EXCEEDED", "quota exceeded")
	}
	return nil
}

func (s *session) addNodes(ctx context.Context, count int64) error {
	changed, err := s.tx.Exec(ctx, `UPDATE filesystems SET node_count=node_count+$2
 WHERE id=$1 AND node_count+$2 >= CASE WHEN state='deleting' THEN 0 ELSE 1 END AND ($2<=0 OR node_count+$2<=$3)`, s.fs, count, s.maxNodes)
	if err != nil {
		return databaseError(err)
	}
	if changed.RowsAffected() != 1 {
		return rpc.Fault(codes.Aborted, "RESOURCE_LIMIT", "node limit exceeded")
	}
	return nil
}

func (s *session) bump(ctx context.Context, ids ...uuid.UUID) error {
	_, err := s.tx.Exec(ctx, `UPDATE nodes SET revision=revision+1,updated_at=now() WHERE id=ANY($1)`, ids)
	return databaseError(err)
}

func (s *session) fetch(ctx context.Context, id uuid.UUID) (Node, error) {
	var node Node
	err := s.tx.QueryRow(ctx, `SELECT `+nodeColumns+`,false FROM nodes n LEFT JOIN files f ON f.node_id=n.id WHERE n.filesystem_id=$1 AND n.id=$2`, s.fs, id).Scan(node.fields()...)
	return node, databaseError(err)
}

func (s *session) depth(ctx context.Context, id uuid.UUID) (int64, error) {
	var depth int64
	err := s.tx.QueryRow(ctx, `WITH RECURSIVE a AS (SELECT id,parent_id,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2
 UNION ALL SELECT n.id,n.parent_id,a.depth+1 FROM a JOIN nodes n ON n.id=a.parent_id AND n.filesystem_id=$2 WHERE a.depth<128)
 SELECT max(depth)::bigint FROM a`, id, s.fs).Scan(&depth)
	return depth, databaseError(err)
}

func (s *Store) CreateNode(ctx context.Context, fs uuid.UUID, mounts []Mount, key uuid.UUID, input CreateNode) (Node, error) {
	actor, err := s.authorize(ctx, fs, "filesystem", authz.NodeCreate)
	if err != nil {
		return Node{}, err
	}
	if key == uuid.Nil {
		return Node{}, rpc.Fault(codes.InvalidArgument, "VALIDATION", "request key required")
	}
	if err = ValidateName(input.Name); err != nil {
		return Node{}, err
	}
	if _, err = pathParts(fs, mounts, input.Parent); err != nil {
		return Node{}, err
	}
	if input.File != nil {
		file := *input.File
		if file.Content == nil {
			file.Content = []byte{}
		}
		input.File = &file
		if err = mediaType(input.File.MediaType); err != nil {
			return Node{}, err
		}
		if err = s.inlineSize(input.File.Content); err != nil {
			return Node{}, err
		}
	}
	hash, err := fingerprint(input)
	if err != nil {
		return Node{}, err
	}
	session, err := s.openSession(ctx, fs, true)
	if err != nil {
		return Node{}, err
	}
	defer session.tx.Rollback(ctx)
	scope := "filesystem/" + fs.String() + "/actor/" + actor.String()
	var savedHash string
	var saved []byte
	err = session.tx.QueryRow(ctx, `SELECT request_hash,result FROM idempotency_keys
 WHERE scope=$1 AND operation='create-node' AND request_key=$2 AND (expires_at IS NULL OR expires_at>now())`, scope, key.String()).Scan(&savedHash, &saved)
	if err == nil {
		if savedHash != hash {
			return Node{}, rpc.Fault(codes.Aborted, "IDEMPOTENCY_CONFLICT", "request key was used for different input")
		}
		var node Node
		if err = json.Unmarshal(saved, &node); err != nil {
			return Node{}, rpc.Fault(codes.Aborted, "INVALID_RECEIPT", "invalid saved receipt")
		}
		return node, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return Node{}, databaseError(err)
	}
	parent, err := session.resolveOne(ctx, mounts, input.Parent)
	if err != nil {
		return Node{}, err
	}
	if err = guard(input.Parent, parent.ID, true); err != nil {
		return Node{}, err
	}
	if err = parent.writable(); err != nil {
		return Node{}, err
	}
	if err = parent.directory(); err != nil {
		return Node{}, err
	}
	if err = session.name(parent.ID, input.Name); err != nil {
		return Node{}, err
	}
	depth, err := session.depth(ctx, parent.ID)
	if err != nil {
		return Node{}, err
	}
	if depth >= maxDepth {
		return Node{}, rpc.Fault(codes.Aborted, "RESOURCE_LIMIT", "tree depth limit exceeded")
	}
	if err = session.addNodes(ctx, 1); err != nil {
		return Node{}, err
	}
	var content []byte
	kind := "directory"
	if input.File != nil {
		kind, content = "file", input.File.Content
	}
	if err = session.usage(ctx, int64(len(content))); err != nil {
		return Node{}, err
	}
	id := uuid.Must(uuid.NewV7())
	_, err = session.tx.Exec(ctx, `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,$4,$5,$6)`, id, fs, parent.ID, input.Name, kind, len(content))
	if err != nil {
		return Node{}, databaseError(err)
	}
	if input.File != nil {
		if content == nil {
			content = []byte{}
		}
		_, err = session.tx.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes,media_type) VALUES($1,'inline',$2,$3)`, id, content, input.File.MediaType)
		if err != nil {
			return Node{}, databaseError(err)
		}
	}
	if err = session.bump(ctx, parent.ID); err != nil {
		return Node{}, err
	}
	node, err := session.fetch(ctx, id)
	if err != nil {
		return Node{}, err
	}
	if input.File != nil {
		if err = session.recordIntent(ctx, node); err != nil {
			return Node{}, err
		}
	}
	saved, err = json.Marshal(node)
	if err != nil {
		return Node{}, err
	}
	_, err = session.tx.Exec(ctx, `INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result,expires_at)
 VALUES($1,'create-node',$2,$3,$4,now()+interval '24 hours') ON CONFLICT(scope,operation,request_key) DO UPDATE
 SET request_hash=excluded.request_hash,result=excluded.result,expires_at=excluded.expires_at WHERE idempotency_keys.expires_at<=now()`, scope, key.String(), hash, saved)
	if err != nil {
		return Node{}, databaseError(err)
	}
	return node, databaseError(session.tx.Commit(ctx))
}

type UpdateNode struct {
	Locator  Locator
	Revision *int64
	Name     *string
	Parent   *Locator
}

func (s *Store) UpdateNode(ctx context.Context, fs uuid.UUID, mounts []Mount, input UpdateNode) (Node, error) {
	if _, err := s.authorize(ctx, fs, "filesystem", authz.NodeUpdate); err != nil {
		return Node{}, err
	}
	if input.Name == nil && input.Parent == nil {
		return Node{}, rpc.Fault(codes.InvalidArgument, "VALIDATION", "node patch is empty")
	}
	session, err := s.openSession(ctx, fs, true)
	if err != nil {
		return Node{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, mounts, input.Locator)
	if err != nil {
		return Node{}, err
	}
	if err = guard(input.Locator, node.ID, false); err != nil {
		return Node{}, err
	}
	if err = node.writable(); err != nil {
		return Node{}, err
	}
	if err = node.revision(input.Revision); err != nil {
		return Node{}, err
	}
	if node.ID == session.root {
		return Node{}, rpc.Fault(codes.Aborted, "ROOT_IMMUTABLE", "root is immutable")
	}
	name := node.Name
	if input.Name != nil {
		name = *input.Name
	}
	parent := *node.ParentID
	if input.Parent != nil {
		destination, err := session.resolveOne(ctx, mounts, *input.Parent)
		if err != nil {
			return Node{}, err
		}
		if err = guard(*input.Parent, destination.ID, true); err != nil {
			return Node{}, err
		}
		if err = destination.writable(); err != nil {
			return Node{}, err
		}
		if err = destination.directory(); err != nil {
			return Node{}, err
		}
		parent = destination.ID
	}
	if err = session.name(parent, name); err != nil {
		return Node{}, err
	}
	if err = session.validateMove(ctx, node.ID, parent); err != nil {
		return Node{}, err
	}
	_, err = session.tx.Exec(ctx, `UPDATE nodes SET name=$2,parent_id=$3 WHERE id=$1`, node.ID, name, parent)
	if err != nil {
		return Node{}, databaseError(err)
	}
	if err = session.bump(ctx, parent, *node.ParentID); err != nil {
		return Node{}, err
	}
	if err = session.bump(ctx, node.ID); err != nil {
		return Node{}, err
	}
	out, err := session.fetch(ctx, node.ID)
	if err != nil {
		return Node{}, err
	}
	return out, databaseError(session.tx.Commit(ctx))
}

func (s *session) cycle(ctx context.Context, id, parent uuid.UUID) error {
	var err error
	var cycle bool
	err = s.tx.QueryRow(ctx, `WITH RECURSIVE a AS (SELECT id,parent_id,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2
 UNION ALL SELECT n.id,n.parent_id,a.depth+1 FROM a JOIN nodes n ON n.id=a.parent_id AND n.filesystem_id=$2 WHERE a.depth<128)
 SELECT EXISTS(SELECT 1 FROM a WHERE id=$3)`, parent, s.fs, id).Scan(&cycle)
	if err != nil {
		return databaseError(err)
	}
	if cycle {
		return rpc.Fault(codes.Aborted, "CYCLE", "move would create a cycle")
	}
	return nil
}

func (s *session) validateMove(ctx context.Context, id, parent uuid.UUID) error {
	if err := s.cycle(ctx, id, parent); err != nil {
		return err
	}

	depth, err := s.depth(ctx, parent)
	if err != nil {
		return err
	}
	var height int64
	err = s.tx.QueryRow(ctx, `WITH RECURSIVE a AS (SELECT id,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2
 UNION ALL SELECT n.id,a.depth+1 FROM a JOIN nodes n ON n.parent_id=a.id AND n.filesystem_id=$2 WHERE a.depth<128)
 SELECT max(depth)::bigint FROM a`, id, s.fs).Scan(&height)
	if err != nil {
		return databaseError(err)
	}
	if depth+1+height > maxDepth {
		return rpc.Fault(codes.Aborted, "RESOURCE_LIMIT", "tree depth limit exceeded")
	}
	return nil
}

func (s *Store) ReplaceContent(ctx context.Context, fs uuid.UUID, mounts []Mount, locator Locator, revision *int64, content []byte, mime string) (Node, error) {
	_, err := s.authorize(ctx, fs, "filesystem", authz.ContentWrite)
	if err != nil {
		return Node{}, err
	}
	if err = s.inlineSize(content); err != nil {
		return Node{}, err
	}
	session, err := s.openSession(ctx, fs, true)
	if err != nil {
		return Node{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, mounts, locator)
	if err != nil {
		return Node{}, err
	}
	if err = guard(locator, node.ID, false); err != nil {
		return Node{}, err
	}
	if err = node.writable(); err != nil {
		return Node{}, err
	}
	if err = node.revision(revision); err != nil {
		return Node{}, err
	}
	if node.ID == session.root {
		return Node{}, rpc.Fault(codes.Aborted, "ROOT_IMMUTABLE", "root is immutable")
	}
	if node.Kind != "file" {
		return Node{}, rpc.Fault(codes.Aborted, "NOT_FILE", "file required")
	}
	if err = mediaType(mime); err != nil {
		return Node{}, err
	}
	if err = session.usage(ctx, int64(len(content))-node.SizeBytes); err != nil {
		return Node{}, err
	}
	if err = session.invalidate(ctx, node.ID); err != nil {
		return Node{}, err
	}
	if err = session.queueObject(ctx, node.ID); err != nil {
		return Node{}, err
	}
	if content == nil {
		content = []byte{}
	}
	_, err = session.tx.Exec(ctx, `UPDATE files SET storage_kind='inline',inline_bytes=$2,object_key=NULL,media_type=$3 WHERE node_id=$1`, node.ID, content, mime)
	if err != nil {
		return Node{}, databaseError(err)
	}
	_, err = session.tx.Exec(ctx, `UPDATE nodes SET size_bytes=$2 WHERE id=$1`, node.ID, len(content))
	if err != nil {
		return Node{}, databaseError(err)
	}
	if err = session.bump(ctx, node.ID); err != nil {
		return Node{}, err
	}
	out, err := session.fetch(ctx, node.ID)
	if err != nil {
		return Node{}, err
	}
	if err = session.recordIntent(ctx, out); err != nil {
		return Node{}, err
	}
	return out, databaseError(session.tx.Commit(ctx))
}
