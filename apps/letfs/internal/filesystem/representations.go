package filesystem

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

const (
	MaxReadBytes   = 4 << 20
	MaxTreeEntries = 10000
)

type FileStat struct {
	Node                                         Node
	StorageKind, RepresentationKind, Fingerprint string
	ReadableSize                                 int64
	NewlineCount                                 *int64
	SHA256                                       *string
}

type fileMetadata struct {
	Node        Node
	Path        string
	Storage     string
	LF          *int64
	SHA         *string
	Generation  int64
	Status      string
	Error       *string
	HasChildren bool
}

const metadataColumns = `,COALESCE(f.storage_kind,''),f.newline_count,f.text_sha256,COALESCE(f.desired_generation,0),COALESCE(f.publication_status,''),f.processing_error,
 EXISTS(SELECT 1 FROM nodes c WHERE c.scope_id=n.scope_id AND c.parent_id=n.id)`

func (m *fileMetadata) fields() []any {
	return append(m.Node.fields(), &m.Storage, &m.LF, &m.SHA, &m.Generation, &m.Status, &m.Error, &m.HasChildren)
}

func readLimit() error {
	return apperr.New(apperr.Limit, "RESOURCE_LIMIT", "read representation exceeds limit")
}

func (s *session) metadata(ctx context.Context, node Node) (fileMetadata, error) {
	m := fileMetadata{Node: node}
	err := s.tx.QueryRow(ctx, `SELECT `+strings.Replace(nodeColumns, "f.context", "NULL::text", 1)+`,$3::boolean`+metadataColumns+`
 FROM nodes n LEFT JOIN files f ON f.node_id=n.id WHERE n.scope_id=$1 AND n.id=$2`, s.scopeID, node.ID, node.readonly).Scan(m.fields()...)
	return m, databaseError(err)
}

type artifactMetadata struct {
	ID        uuid.UUID           `json:"id"`
	ParentID  *uuid.UUID          `json:"parent_id"`
	Name      string              `json:"name"`
	Path      string              `json:"path"`
	Kind      string              `json:"kind"`
	Revision  int64               `json:"revision"`
	Size      int64               `json:"size_bytes"`
	MediaType *string             `json:"media_type,omitempty"`
	Children  []*artifactMetadata `json:"children,omitempty"`
}

// Batch original-file subtrees so a tree page does not issue one RPC/SQL query per file.
func (s *session) artifactTrees(ctx context.Context, files []fileMetadata) (map[uuid.UUID][]*artifactMetadata, error) {
	ids := []uuid.UUID{}
	for _, file := range files {
		if file.Storage != "text" && file.Node.Kind == "file" && file.HasChildren {
			ids = append(ids, file.Node.ID)
		}
	}
	result := make(map[uuid.UUID][]*artifactMetadata)
	if len(ids) == 0 {
		return result, nil
	}
	rows, err := s.tx.Query(ctx, `WITH RECURSIVE tree AS (
 SELECT n.id AS owner,n.id,n.parent_id,n.name,n.kind,n.revision,n.size_bytes,''::text COLLATE "C" AS path,0 AS depth FROM nodes n WHERE n.scope_id=$1 AND n.id=ANY($2)
 UNION ALL SELECT t.owner,n.id,n.parent_id,n.name,n.kind,n.revision,n.size_bytes,CASE WHEN t.path='' THEN n.name ELSE t.path||'/'||n.name END,t.depth+1
 FROM tree t JOIN nodes n ON n.parent_id=t.id AND n.scope_id=$1 WHERE t.depth<128)
 SELECT t.owner,t.id,t.parent_id,t.name,t.path,t.kind,t.revision,t.size_bytes,f.media_type,
 t.depth=128 AND EXISTS(SELECT 1 FROM nodes c WHERE c.scope_id=$1 AND c.parent_id=t.id)
 FROM tree t LEFT JOIN files f ON f.node_id=t.id
 WHERE t.depth>0 ORDER BY t.owner,t.path,t.id`, s.scopeID, ids)
	if err != nil {
		return nil, databaseError(err)
	}
	defer rows.Close()
	parents := map[uuid.UUID]map[uuid.UUID]*artifactMetadata{}
	counts := map[uuid.UUID]int{}
	total := 0
	for rows.Next() {
		var owner uuid.UUID
		var truncated bool
		item := new(artifactMetadata)
		if err = rows.Scan(&owner, &item.ID, &item.ParentID, &item.Name, &item.Path, &item.Kind, &item.Revision, &item.Size, &item.MediaType, &truncated); err != nil {
			return nil, databaseError(err)
		}
		counts[owner]++
		encoded, err := json.Marshal(item)
		if err != nil {
			return nil, err
		}
		total += len(encoded)
		if truncated || counts[owner] > MaxTreeEntries || total > MaxReadBytes || len(item.Path) > 4096 {
			return nil, readLimit()
		}
		if parents[owner] == nil {
			parents[owner] = map[uuid.UUID]*artifactMetadata{}
		}
		parents[owner][item.ID] = item
		if item.ParentID != nil && *item.ParentID == owner {
			result[owner] = append(result[owner], item)
		} else if item.ParentID != nil && parents[owner][*item.ParentID] != nil {
			parent := parents[owner][*item.ParentID]
			parent.Children = append(parent.Children, item)
		} else {
			return nil, apperr.New(apperr.Internal, "INTERNAL", "invalid artifact hierarchy")
		}
	}
	return result, databaseError(rows.Err())
}

func representation(m fileMetadata, tree []*artifactMetadata) (FileStat, []byte, error) {
	stat := FileStat{Node: m.Node, StorageKind: m.Storage, RepresentationKind: m.Node.Kind}
	var body []byte
	var digest string
	switch {
	case m.Node.Kind == "directory":
		digest = fmt.Sprintf("directory:%d", m.Node.Revision)
	case m.Storage == "text":
		if m.SHA == nil || m.LF == nil {
			return FileStat{}, nil, apperr.New(apperr.Internal, "INTERNAL", "invalid text metadata")
		}
		stat.RepresentationKind = "text"
		stat.ReadableSize = m.Node.SizeBytes
		stat.SHA256 = m.SHA
		stat.NewlineCount = m.LF
		digest = *m.SHA
	case m.Storage == "inline" || m.Storage == "object":
		stat.RepresentationKind = "blob_metadata"
		if tree == nil {
			tree = []*artifactMetadata{}
		}
		value := struct {
			Version    int                 `json:"version"`
			ID         uuid.UUID           `json:"id"`
			Name       string              `json:"name"`
			MediaType  *string             `json:"media_type,omitempty"`
			Size       int64               `json:"size_bytes"`
			Revision   int64               `json:"revision"`
			Generation int64               `json:"processing_generation"`
			Status     string              `json:"processing_status"`
			Error      *string             `json:"processing_error,omitempty"`
			Artifacts  []*artifactMetadata `json:"artifacts"`
		}{1, m.Node.ID, m.Node.Name, m.Node.MediaType, m.Node.SizeBytes, m.Node.Revision, m.Generation, m.Status, m.Error, tree}
		var err error
		body, err = json.Marshal(value)
		if err != nil {
			return FileStat{}, nil, err
		}
		if len(body) > MaxReadBytes {
			return FileStat{}, nil, readLimit()
		}
		sha := sha256.Sum256(body)
		digest = hex.EncodeToString(sha[:])
		lines := int64(bytes.Count(body, []byte{'\n'}))
		stat.ReadableSize = int64(len(body))
		stat.NewlineCount = &lines
		stat.SHA256 = &digest
	default:
		return FileStat{}, nil, apperr.New(apperr.Internal, "INTERNAL", "invalid file metadata")
	}
	// Identity and revision prevent a reused path with equal bytes from matching an old observation.
	stat.Fingerprint = fmt.Sprintf("v1:%s:%d:%s", m.Node.ID, m.Node.Revision, digest)
	return stat, body, nil
}

func (s *session) fileRepresentation(ctx context.Context, node Node) (FileStat, []byte, error) {
	m, err := s.metadata(ctx, node)
	if err != nil {
		return FileStat{}, nil, err
	}
	trees, err := s.artifactTrees(ctx, []fileMetadata{m})
	if err != nil {
		return FileStat{}, nil, err
	}
	return representation(m, trees[node.ID])
}

func (s *Store) Stat(ctx context.Context, scopeID uuid.UUID, locator Locator, contentCheck bool) (FileStat, error) {
	action := authz.ScopeReadMetadata
	if contentCheck {
		action = authz.ScopeReadContent
	}
	if _, err := s.authorize(ctx, scopeID, "scope", action); err != nil {
		return FileStat{}, err
	}
	session, err := s.openSession(ctx, scopeID, false)
	if err != nil {
		return FileStat{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, locator)
	if err != nil {
		return FileStat{}, err
	}
	if locator.ExpectedNodeID != nil && *locator.ExpectedNodeID != node.ID {
		return FileStat{}, apperr.New(apperr.Conflict, "TARGET_MISMATCH", "target mismatch")
	}
	stat, _, err := session.fileRepresentation(ctx, node)
	return stat, err
}
