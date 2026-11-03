package filesystem

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/search"
	"github.com/qninhdt/openlet/packages/go/authz"
)

func excerpt(text, query string, limit int) string {
	lower, position := strings.ToLower(text), 0
	found := false
	for _, word := range strings.Fields(query) {
		if at := strings.Index(lower, strings.ToLower(word)); at >= 0 && (!found || at < position) {
			position, found = at, true
		}
	}
	start := max(0, utf8.RuneCountInString(lower[:position])-limit/4)
	runes := []rune(text)
	start = min(start, len(runes))
	return string(runes[start:min(start+limit, len(runes))])
}

func (s *Store) hydrateSearch(ctx context.Context, fs uuid.UUID, mounts []Mount, input SearchInput, points []search.Point) (map[int]SearchResult, error) {
	session, err := s.openSession(ctx, fs, false)
	if err != nil {
		return nil, err
	}
	defer session.tx.Rollback(ctx)
	root, path, err := session.searchRoot(ctx, mounts, input.Filters)
	if err != nil {
		return nil, err
	}
	type request struct {
		Index      int       `json:"idx"`
		SourceID   uuid.UUID `json:"source_id"`
		FileID     uuid.UUID `json:"file_id"`
		Generation int64     `json:"generation"`
	}
	requests := make([]request, 0, len(points))
	for i, point := range points {
		p := point.Payload
		if p.FilesystemID == fs && p.EmbeddingModel == s.IndexSpace.Model && p.VectorDimension == s.IndexSpace.Dimension {
			requests = append(requests, request{i, p.SourceID, p.FileID, p.Generation})
		}
	}
	data, err := json.Marshal(requests)
	if err != nil {
		return nil, err
	}
	query := fmt.Sprintf(`%s,req AS (SELECT * FROM jsonb_to_recordset($10) AS p(idx int,source_id uuid,file_id uuid,generation bigint)),
 ancestors AS (SELECT p.idx,p.source_id,p.generation,n.id,n.parent_id,0 AS depth,jsonb_build_array(jsonb_build_object('node_id',n.id,'filename',n.name)) AS breadcrumb FROM req p JOIN nodes n ON n.id=p.file_id AND n.filesystem_id=$1
 UNION ALL SELECT a.idx,a.source_id,a.generation,n.id,n.parent_id,a.depth+1,jsonb_build_array(jsonb_build_object('node_id',n.id,'filename',n.name))||a.breadcrumb
 FROM ancestors a JOIN nodes n ON n.id=a.parent_id WHERE n.filesystem_id=$1 AND a.id!=a.source_id AND a.depth<128)
 SELECT a.idx,%s,false,l.path,a.breadcrumb FROM ancestors a JOIN live l ON l.id=a.source_id JOIN nodes n ON n.id=l.id JOIN files f ON f.node_id=n.id
 WHERE a.id=a.source_id AND n.kind='file' AND f.desired_generation=a.generation
 AND f.publication_status='ready' %s`,
		searchLive, strings.Replace(nodeColumns, "f.context", "NULL::text", 1), searchFiltersSQL)
	f := input.Filters
	rows, err := session.tx.Query(ctx, query, fs, root, path, f.SemanticType, f.MediaType, f.CreatedAfter, f.CreatedBefore, f.UpdatedAfter, f.UpdatedBefore, data)
	if err != nil {
		return nil, databaseError(err)
	}
	defer rows.Close()
	result := make(map[int]SearchResult)
	for rows.Next() {
		var index int
		var item SearchResult
		var breadcrumb []Breadcrumb
		fields := append([]any{&index}, item.Node.fields()...)
		if err = rows.Scan(append(fields, &item.Path, &breadcrumb)...); err != nil {
			return nil, databaseError(err)
		}
		if index < 0 || index >= len(points) {
			return nil, search.Dependency()
		}
		point := points[index]
		item.Matched = &SearchMatch{FileID: point.Payload.FileID, Breadcrumb: breadcrumb, Snippet: excerpt(point.Payload.Text, input.Query, 600)}
		result[index] = item
	}
	return result, databaseError(rows.Err())
}

func (s *Store) SemanticSearch(ctx context.Context, fs uuid.UUID, mounts []Mount, input SearchInput) (SearchPage, error) {
	actor, err := s.authorize(ctx, fs, "filesystem", authz.Search)
	if err != nil {
		return SearchPage{}, err
	}
	limit, err := input.validate(true)
	if err != nil {
		return SearchPage{}, err
	}
	binding, err := s.searchBinding(fs, actor, mounts, input, true)
	if err != nil {
		return SearchPage{}, err
	}
	cursor, err := decodeSearchCursor(input.Cursor, binding)
	if err != nil {
		return SearchPage{}, err
	}
	// Validate the parent and current filesystem before sending caller text to providers.
	if _, err = s.hydrateSearch(ctx, fs, mounts, input, nil); err != nil {
		return SearchPage{}, err
	}
	if s.AI == nil || s.Search == nil || s.IndexSpace.Validate() != nil {
		return SearchPage{}, search.Dependency()
	}
	vector, err := s.AI.Embed(ctx, input.Query, s.IndexSpace.Model, s.IndexSpace.Dimension)
	if err != nil {
		return SearchPage{}, err
	}
	seen, previous := make(map[uuid.UUID]bool), make(map[uuid.UUID]bool)
	for _, id := range cursor.Seen {
		seen[id], previous[id] = true, true
	}
	perSource := make(map[uuid.UUID]int)
	selected := make([]search.Point, 0, 64)
	exhausted := false
	for range 3 {
		if cursor.Offset >= 10000 || len(seen) >= 256 {
			exhausted = true
			break
		}
		points, err := s.Search.Query(ctx, s.IndexSpace.Collection, fs, strings.TrimSpace(input.Query), vector, cursor.Offset)
		if err != nil {
			return SearchPage{}, err
		}
		if len(points) == 0 {
			exhausted = true
			break
		}
		valid, err := s.hydrateSearch(ctx, fs, mounts, input, points)
		if err != nil {
			return SearchPage{}, err
		}
		consumed := 0
		for i, point := range points {
			if len(selected) >= 64 || cursor.Offset >= 10000 {
				break
			}
			consumed++
			cursor.Offset++
			if _, ok := valid[i]; !ok {
				continue
			}
			id := point.Payload.SourceID
			if previous[id] || perSource[id] >= 3 {
				continue
			}
			if !seen[id] && len(seen)-len(previous) >= int(limit) {
				consumed--
				cursor.Offset--
				break
			}
			seen[id] = true
			perSource[id]++
			selected = append(selected, point)
		}
		if consumed < len(points) {
			break
		}
		if len(points) < 80 {
			exhausted = true
			break
		}
		if len(seen)-len(previous) >= int(limit) {
			break
		}
	}
	result := SearchPage{Items: []SearchResult{}}
	order := make([]int, len(selected))
	for i := range order {
		order[i] = i
	}
	if len(selected) > 0 {
		documents := make([]string, len(selected))
		for i, point := range selected {
			documents[i] = excerpt(point.Payload.Text, input.Query, 1024)
		}
		ranked, err := s.AI.Rerank(ctx, input.Query, documents)
		if err != nil {
			result.Degraded = true
			reason := "RERANK_UNAVAILABLE"
			result.DegradedReason = &reason
		} else {
			order = ranked
		}
	}
	// Provider latency may overlap trash, replacement or revocation; return current facts only.
	if _, err = s.authorize(ctx, fs, "filesystem", authz.Search); err != nil {
		return SearchPage{}, err
	}
	current, err := s.hydrateSearch(ctx, fs, mounts, input, selected)
	if err != nil {
		return SearchPage{}, err
	}
	emitted := make(map[uuid.UUID]bool)
	for _, i := range order {
		point := selected[i]
		if item, ok := current[i]; ok && !emitted[point.Payload.SourceID] {
			emitted[point.Payload.SourceID] = true
			result.Items = append(result.Items, item)
		}
	}
	cursor.Seen = make([]uuid.UUID, 0, len(seen))
	for id := range seen {
		cursor.Seen = append(cursor.Seen, id)
	}
	slices.SortFunc(cursor.Seen, func(a, b uuid.UUID) int { return strings.Compare(a.String(), b.String()) })
	if !exhausted && len(cursor.Seen) < 256 && cursor.Offset < 10000 {
		result.NextCursor, err = encodeSearchCursor(cursor)
		if err != nil {
			return SearchPage{}, err
		}
	}
	return result, nil
}
