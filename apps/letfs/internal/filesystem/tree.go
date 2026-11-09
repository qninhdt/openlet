package filesystem

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"strings"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type TreeOptions struct {
	Depth           *int32
	Cursor          *string
	Limit, MaxBytes *int32
}

type TreeEntry struct {
	Path string
	Stat FileStat
}
type TreePage struct {
	Items      []TreeEntry
	NextCursor *string
	Complete   bool
}
type treeCursor struct {
	Binding string    `json:"binding"`
	Path    string    `json:"path"`
	ID      uuid.UUID `json:"id"`
}

func (s *Store) ReadTree(ctx context.Context, scopeID uuid.UUID, root Locator, options TreeOptions) (TreePage, error) {
	depth, limit, maxBytes := int32(maxDepth), int32(MaxTreeEntries), int32(MaxReadBytes)
	if options.Depth != nil {
		depth = *options.Depth
	}
	if options.Limit != nil {
		limit = *options.Limit
	}
	if options.MaxBytes != nil {
		maxBytes = *options.MaxBytes
	}
	invalid := apperr.New(apperr.Invalid, "VALIDATION", "invalid tree page")
	if depth < 0 || depth > maxDepth || limit < 1 || limit > MaxTreeEntries || maxBytes < 1 || maxBytes > MaxReadBytes {
		return TreePage{}, invalid
	}
	actor, err := s.authorize(ctx, scopeID, "scope", authz.ScopeReadMetadata)
	if err != nil {
		return TreePage{}, err
	}
	session, err := s.openSession(ctx, scopeID, false)
	if err != nil {
		return TreePage{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, root)
	if err != nil {
		return TreePage{}, err
	}
	if root.ExpectedNodeID != nil && *root.ExpectedNodeID != node.ID {
		return TreePage{}, apperr.New(apperr.Conflict, "TARGET_MISMATCH", "target mismatch")
	}
	bound := session.root
	if root.RootID != nil {
		bound = *root.RootID
	}
	binding, err := fingerprint(struct {
		Actor              string
		Scope, Bound, Root uuid.UUID
		Depth              int32
	}{actor.String(), scopeID, bound, node.ID, depth})
	if err != nil {
		return TreePage{}, err
	}
	cursor := treeCursor{Binding: binding}
	if options.Cursor != nil {
		if len(*options.Cursor) > 16384 {
			return TreePage{}, invalid
		}
		body, e := base64.RawURLEncoding.DecodeString(*options.Cursor)
		if e != nil || json.Unmarshal(body, &cursor) != nil || cursor.Binding != binding || len(cursor.Path) > 4096 || cursor.Path == "" || cursor.ID == uuid.Nil {
			return TreePage{}, invalid
		}
	}
	rows, err := session.tx.Query(ctx, `WITH RECURSIVE tree AS (
 SELECT n.*,''::text COLLATE "C" AS path,0 AS depth,$7::boolean AS readonly FROM nodes n WHERE n.scope_id=$1 AND n.id=$2
 UNION ALL SELECT n.*,CASE WHEN t.path='' THEN n.name ELSE t.path||'/'||n.name END,t.depth+1,t.readonly OR t.kind='file'
 FROM tree t JOIN nodes n ON n.parent_id=t.id AND n.scope_id=$1 WHERE t.depth<$3)
 SELECT `+strings.Replace(nodeColumns, "f.context", "NULL::text", 1)+`,n.readonly`+metadataColumns+`,n.path FROM tree n LEFT JOIN files f ON f.node_id=n.id
 WHERE n.depth>0 AND (n.path>$4 OR (n.path=$4 AND n.id>$5)) ORDER BY n.path,n.id LIMIT $6`, scopeID, node.ID, depth, cursor.Path, cursor.ID, limit+1, node.readonly)
	if err != nil {
		return TreePage{}, databaseError(err)
	}
	files := []fileMetadata{}
	for rows.Next() {
		m := fileMetadata{}
		if err = rows.Scan(append(m.fields(), &m.Path)...); err != nil {
			rows.Close()
			return TreePage{}, databaseError(err)
		}
		if len(m.Path) > 4096 {
			rows.Close()
			return TreePage{}, readLimit()
		}
		files = append(files, m)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return TreePage{}, databaseError(err)
	}
	hasMore := len(files) > int(limit)
	if hasMore {
		files = files[:limit]
	}
	trees, err := session.artifactTrees(ctx, files)
	if err != nil {
		return TreePage{}, err
	}
	page := TreePage{Items: []TreeEntry{}, Complete: !hasMore}
	total := 0
	for _, m := range files {
		stat, _, e := representation(m, trees[m.Node.ID])
		if e != nil {
			return TreePage{}, e
		}
		entry := TreeEntry{Path: m.Path, Stat: stat}
		encoded, e := json.Marshal(entry)
		if e != nil {
			return TreePage{}, e
		}
		if total+len(encoded) > int(maxBytes) {
			if len(page.Items) == 0 {
				return TreePage{}, readLimit()
			}
			page.Complete = false
			break
		}
		total += len(encoded)
		page.Items = append(page.Items, entry)
	}
	if !page.Complete {
		last := page.Items[len(page.Items)-1]
		body, e := json.Marshal(treeCursor{Binding: binding, Path: last.Path, ID: last.Stat.Node.ID})
		if e != nil {
			return TreePage{}, e
		}
		raw := base64.RawURLEncoding.EncodeToString(body)
		page.NextCursor = &raw
	}
	return page, nil
}
