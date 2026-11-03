package filesystem

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type SearchFilters struct {
	Parent        *Locator   `json:"parent,omitempty"`
	SemanticType  *string    `json:"type,omitempty"`
	MediaType     *string    `json:"media_type,omitempty"`
	CreatedAfter  *time.Time `json:"created_after,omitempty"`
	CreatedBefore *time.Time `json:"created_before,omitempty"`
	UpdatedAfter  *time.Time `json:"updated_after,omitempty"`
	UpdatedBefore *time.Time `json:"updated_before,omitempty"`
}

type SearchInput struct {
	Query     string        `json:"query"`
	Filters   SearchFilters `json:"filters"`
	Limit     *int32        `json:"limit,omitempty"`
	Cursor    *string       `json:"cursor,omitempty"`
	Sort      *string       `json:"sort,omitempty"`
	Direction *string       `json:"direction,omitempty"`
}

type Breadcrumb struct {
	NodeID   uuid.UUID `json:"node_id"`
	Filename string    `json:"filename"`
}

type SearchMatch struct {
	FileID     uuid.UUID    `json:"file_id"`
	Breadcrumb []Breadcrumb `json:"breadcrumb"`
	Snippet    string       `json:"snippet"`
}

type SearchResult struct {
	Node    Node
	Path    string
	Matched *SearchMatch
}

type SearchPage struct {
	Items          []SearchResult
	NextCursor     *string
	Degraded       bool
	DegradedReason *string
}

type searchCursor struct {
	Binding string      `json:"binding"`
	Value   string      `json:"value"`
	ID      *uuid.UUID  `json:"id"`
	Offset  int         `json:"offset"`
	Seen    []uuid.UUID `json:"seen"`
}

func (input SearchInput) validate(semantic bool) (int32, error) {
	limit, max := int32(20), int32(100)
	if semantic {
		max = 50
	}
	if input.Limit != nil {
		limit = *input.Limit
	}
	invalid := enrichmentValidation("invalid search input")
	if limit < 1 || limit > max || len(input.Query) > 2000 || !utf8.ValidString(input.Query) || strings.ContainsRune(input.Query, 0) || semantic && strings.TrimSpace(input.Query) == "" {
		return 0, invalid
	}
	for _, field := range []struct {
		value *string
		limit int
	}{{input.Filters.SemanticType, 100}, {input.Filters.MediaType, 200}} {
		if field.value != nil && (len(*field.value) > field.limit || !utf8.ValidString(*field.value) || strings.ContainsRune(*field.value, 0)) {
			return 0, invalid
		}
	}
	for _, pair := range [][2]*time.Time{{input.Filters.CreatedAfter, input.Filters.CreatedBefore}, {input.Filters.UpdatedAfter, input.Filters.UpdatedBefore}} {
		if pair[0] != nil && pair[1] != nil && pair[0].After(*pair[1]) {
			return 0, invalid
		}
	}
	if input.Sort != nil && (*input.Sort != "name" && *input.Sort != "created_at" && *input.Sort != "updated_at") || input.Direction != nil && (*input.Direction != "asc" && *input.Direction != "desc") || semantic && (input.Sort != nil || input.Direction != nil) {
		return 0, invalid
	}
	return limit, nil
}

func (s *Store) searchBinding(fs, actor uuid.UUID, mounts []Mount, input SearchInput, semantic bool) (string, error) {
	input.Cursor, input.Query = nil, strings.TrimSpace(input.Query)
	var space *VectorSpace
	reranker := ""
	if semantic {
		space = &s.IndexSpace
		if s.AI != nil {
			reranker = s.AI.RerankModel
		}
	}
	return fingerprint(struct {
		Filesystem uuid.UUID    `json:"filesystem"`
		Actor      uuid.UUID    `json:"actor"`
		Mounts     []Mount      `json:"mounts"`
		Input      SearchInput  `json:"input"`
		Semantic   bool         `json:"semantic"`
		Space      *VectorSpace `json:"vector_space"`
		Reranker   string       `json:"reranker"`
	}{fs, actor, mounts, input, semantic, space, reranker})
}

func decodeSearchCursor(raw *string, binding string) (searchCursor, error) {
	result := searchCursor{Binding: binding}
	if raw == nil {
		return result, nil
	}
	invalid := enrichmentValidation("invalid search cursor")
	if len(*raw) > 16384 {
		return result, invalid
	}
	data, err := base64.RawURLEncoding.DecodeString(*raw)
	if err != nil {
		return result, invalid
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&result) != nil || decoder.Decode(new(any)) != io.EOF || result.Binding != binding || result.Offset < 0 || result.Offset > 10000 || len(result.Seen) > 256 || len(result.Value) > 300 {
		return result, invalid
	}
	seen := make(map[uuid.UUID]bool, len(result.Seen))
	for _, id := range result.Seen {
		if seen[id] {
			return result, invalid
		}
		seen[id] = true
	}
	return result, nil
}

func encodeSearchCursor(value searchCursor) (*string, error) {
	data, err := json.Marshal(value)
	if err != nil {
		return nil, err
	}
	encoded := base64.RawURLEncoding.EncodeToString(data)
	return &encoded, nil
}

// Stop traversal at original files so generated descendants cannot become search roots.
const searchLive = `WITH RECURSIVE live AS (
 SELECT n.id,n.kind,$3::text COLLATE "C" AS path,0 AS depth FROM nodes n WHERE n.id=$2 AND n.filesystem_id=$1
 UNION ALL SELECT n.id,n.kind,rtrim(l.path,'/')||'/'||n.name,l.depth+1 FROM nodes n JOIN live l ON n.parent_id=l.id WHERE n.filesystem_id=$1 AND l.kind='directory' AND l.depth<128) `

const searchFiltersSQL = ` AND ($4::text IS NULL OR f.semantic_type=$4) AND ($5::text IS NULL OR f.media_type=$5)
 AND ($6::timestamptz IS NULL OR n.created_at>=$6) AND ($7::timestamptz IS NULL OR n.created_at<=$7)
 AND ($8::timestamptz IS NULL OR n.updated_at>=$8) AND ($9::timestamptz IS NULL OR n.updated_at<=$9) `

func (s *session) searchRoot(ctx context.Context, mounts []Mount, filter SearchFilters) (uuid.UUID, string, error) {
	locator := Locator{NodeID: &s.root}
	if filter.Parent != nil {
		locator = *filter.Parent
	}
	node, err := s.resolveOne(ctx, mounts, locator)
	if err != nil {
		return uuid.Nil, "", err
	}
	if err = node.directory(); err != nil {
		return uuid.Nil, "", err
	}
	if err = node.writable(); err != nil {
		return uuid.Nil, "", err
	}
	var parts []string
	err = s.tx.QueryRow(ctx, `WITH RECURSIVE a AS (
 SELECT id,parent_id,name,0 AS depth FROM nodes WHERE id=$1 AND filesystem_id=$2
 UNION ALL SELECT n.id,n.parent_id,n.name,a.depth+1 FROM nodes n JOIN a ON n.id=a.parent_id WHERE n.filesystem_id=$2 AND a.id!=$3 AND a.depth<128)
 SELECT coalesce(array_agg(name ORDER BY depth DESC) FILTER(WHERE id!=$3),ARRAY[]::text[]) FROM a`, node.ID, s.fs, s.root).Scan(&parts)
	if err != nil {
		return uuid.Nil, "", databaseError(err)
	}
	for _, mount := range mounts {
		if mount.FilesystemID == s.fs {
			path := mount.Path
			if len(parts) > 0 {
				path = strings.TrimRight(path, "/") + "/" + strings.Join(parts, "/")
			}
			return node.ID, path, nil
		}
	}
	return uuid.Nil, "", uploadState("INVALID_SEARCH_SCOPE")
}

func (s *Store) SearchFiles(ctx context.Context, fs uuid.UUID, mounts []Mount, input SearchInput) (SearchPage, error) {
	actor, err := s.authorize(ctx, fs, "filesystem", authz.Search)
	if err != nil {
		return SearchPage{}, err
	}
	limit, err := input.validate(false)
	if err != nil {
		return SearchPage{}, err
	}
	binding, err := s.searchBinding(fs, actor, mounts, input, false)
	if err != nil {
		return SearchPage{}, err
	}
	cursor, err := decodeSearchCursor(input.Cursor, binding)
	if err != nil {
		return SearchPage{}, err
	}
	session, err := s.openSession(ctx, fs, false)
	if err != nil {
		return SearchPage{}, err
	}
	defer session.tx.Rollback(ctx)
	root, path, err := session.searchRoot(ctx, mounts, input.Filters)
	if err != nil {
		return SearchPage{}, err
	}
	value := `n.name`
	if input.Sort != nil && *input.Sort != "name" {
		value = fmt.Sprintf(`to_char(n.%s AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US') COLLATE "C"`, *input.Sort)
	}
	op, direction := ">", "ASC"
	if input.Direction != nil && *input.Direction == "desc" {
		op, direction = "<", "DESC"
	}
	// Only validated fixed sort/direction choices enter SQL; all caller values remain parameters.
	query := fmt.Sprintf(`%s SELECT %s,false,l.path,%s AS sort_value FROM live l JOIN nodes n ON n.id=l.id JOIN files f ON f.node_id=n.id
 WHERE n.kind='file' %s AND (strpos(lower(n.name),lower($10))>0 OR strpos(lower(coalesce(f.title,'')),lower($10))>0)
 AND ($11::uuid IS NULL OR (%s,n.id)%s($12::text,$11::uuid)) ORDER BY %s %s,n.id %s LIMIT $13`,
		searchLive, strings.Replace(nodeColumns, "f.context", "NULL::text", 1), value, searchFiltersSQL, value, op, value, direction, direction)
	f := input.Filters
	rows, err := session.tx.Query(ctx, query, fs, root, path, f.SemanticType, f.MediaType, f.CreatedAfter, f.CreatedBefore, f.UpdatedAfter, f.UpdatedBefore, strings.TrimSpace(input.Query), cursor.ID, cursor.Value, limit+1)
	if err != nil {
		return SearchPage{}, databaseError(err)
	}
	defer rows.Close()
	result := SearchPage{Items: []SearchResult{}}
	var last string
	for rows.Next() {
		var item SearchResult
		var sortValue string
		if err = rows.Scan(append(item.Node.fields(), &item.Path, &sortValue)...); err != nil {
			return SearchPage{}, databaseError(err)
		}
		if len(result.Items) == int(limit) {
			id := result.Items[len(result.Items)-1].Node.ID
			result.NextCursor, err = encodeSearchCursor(searchCursor{Binding: binding, Value: last, ID: &id})
			if err != nil {
				return SearchPage{}, err
			}
			break
		}
		result.Items, last = append(result.Items, item), sortValue
	}
	return result, databaseError(rows.Err())
}
