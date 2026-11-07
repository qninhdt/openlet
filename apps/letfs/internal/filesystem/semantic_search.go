package filesystem

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/search"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type SemanticSearchInput struct {
	Query   string        `json:"query"`
	Filters SearchFilters `json:"filters"`
	Limit   *int32        `json:"limit,omitempty"`
}

type SemanticSearchResults struct {
	Items          []SearchResult
	Degraded       bool
	DegradedReason *string
}

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

func (s *Store) hydrateSearch(ctx context.Context, scopeID uuid.UUID, input SemanticSearchInput, points []search.Point) (map[int]SearchResult, error) {
	session, err := s.openSession(ctx, scopeID, false)
	if err != nil {
		return nil, err
	}
	defer session.tx.Rollback(ctx)
	root, path, err := session.searchRoot(ctx, input.Filters)
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
		if p.ScopeID == scopeID && p.EmbeddingModel == s.IndexSpace.Model && p.VectorDimension == s.IndexSpace.Dimension {
			requests = append(requests, request{i, p.SourceID, p.FileID, p.Generation})
		}
	}
	data, err := json.Marshal(requests)
	if err != nil {
		return nil, err
	}
	// Validate only provider candidates against current ancestry, rather than walking the whole scope.
	query := fmt.Sprintf(`WITH RECURSIVE req AS (SELECT * FROM jsonb_to_recordset($10) AS p(idx int,source_id uuid,file_id uuid,generation bigint)),
 live AS (
 SELECT DISTINCT n.id AS source_id,n.id,n.parent_id,n.name::text COLLATE "C" AS path,0 AS depth FROM req p JOIN nodes n ON n.id=p.source_id AND n.scope_id=$1
 UNION ALL SELECT l.source_id,n.id,n.parent_id,CASE WHEN n.id=$2 THEN rtrim($3,'/')||'/'||l.path ELSE n.name||'/'||l.path END,l.depth+1
 FROM live l JOIN nodes n ON n.id=l.parent_id AND n.scope_id=$1 WHERE l.id<>$2 AND n.kind='directory' AND l.depth<128),
 ancestors AS (SELECT p.idx,p.source_id,p.generation,n.id,n.parent_id,0 AS depth,jsonb_build_array(jsonb_build_object('node_id',n.id,'filename',n.name)) AS breadcrumb FROM req p JOIN nodes n ON n.id=p.file_id AND n.scope_id=$1
 UNION ALL SELECT a.idx,a.source_id,a.generation,n.id,n.parent_id,a.depth+1,jsonb_build_array(jsonb_build_object('node_id',n.id,'filename',n.name))||a.breadcrumb
 FROM ancestors a JOIN nodes n ON n.id=a.parent_id WHERE n.scope_id=$1 AND a.id!=a.source_id AND a.depth<128)
 SELECT a.idx,%s,false,l.path,a.breadcrumb FROM ancestors a JOIN live l ON l.source_id=a.source_id AND l.id=$2 JOIN nodes n ON n.id=l.source_id JOIN files f ON f.node_id=n.id
 WHERE a.id=a.source_id AND n.kind='file' AND f.desired_generation=a.generation
 AND f.publication_status='ready' %s`,
		strings.Replace(nodeColumns, "f.context", "NULL::text", 1), searchFiltersSQL)
	f := input.Filters
	rows, err := session.tx.Query(ctx, query, scopeID, root, path, f.SemanticType, f.MediaType, f.CreatedAfter, f.CreatedBefore, f.UpdatedAfter, f.UpdatedBefore, data)
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

func (s *Store) SemanticSearch(ctx context.Context, scopeID uuid.UUID, input SemanticSearchInput) (SemanticSearchResults, error) {
	_, err := s.authorize(ctx, scopeID, "scope", authz.ScopeReadContent)
	if err != nil {
		return SemanticSearchResults{}, err
	}
	limit, err := (SearchInput{Query: input.Query, Filters: input.Filters, Limit: input.Limit}).validate(true)
	if err != nil {
		return SemanticSearchResults{}, err
	}
	var filesystemID uuid.UUID
	var allowIndexing bool
	if err = s.DB.QueryRow(ctx, `SELECT filesystem_id,allow_indexing FROM scopes WHERE id=$1`, scopeID).Scan(&filesystemID, &allowIndexing); err != nil {
		return SemanticSearchResults{}, databaseError(err)
	}
	// Validate scope before sending caller text to providers.
	if _, err = s.hydrateSearch(ctx, scopeID, input, nil); err != nil {
		return SemanticSearchResults{}, err
	}
	if !allowIndexing {
		return SemanticSearchResults{Items: []SearchResult{}}, nil
	}
	if s.AI == nil || s.Search == nil || s.IndexSpace.Validate() != nil {
		return SemanticSearchResults{}, search.Dependency()
	}
	vector, err := s.AI.Embed(ctx, input.Query, s.IndexSpace.Model, s.IndexSpace.Dimension)
	if err != nil {
		return SemanticSearchResults{}, err
	}
	points, err := s.Search.Query(ctx, s.IndexSpace.Collection, filesystemID, scopeID, strings.TrimSpace(input.Query), vector)
	if err != nil {
		return SemanticSearchResults{}, err
	}
	valid, err := s.hydrateSearch(ctx, scopeID, input, points)
	if err != nil {
		return SemanticSearchResults{}, err
	}
	perSource := make(map[uuid.UUID]int)
	selected := make([]search.Point, 0, 64)
	for i, point := range points {
		if len(selected) == 64 {
			break
		}
		if _, ok := valid[i]; !ok || perSource[point.Payload.SourceID] == 3 {
			continue
		}
		perSource[point.Payload.SourceID]++
		selected = append(selected, point)
	}
	result := SemanticSearchResults{Items: []SearchResult{}}
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
	if _, err = s.authorize(ctx, scopeID, "scope", authz.ScopeReadContent); err != nil {
		return SemanticSearchResults{}, err
	}
	current, err := s.hydrateSearch(ctx, scopeID, input, selected)
	if err != nil {
		return SemanticSearchResults{}, err
	}
	emitted := make(map[uuid.UUID]bool)
	for _, i := range order {
		point := selected[i]
		if item, ok := current[i]; ok && !emitted[point.Payload.SourceID] {
			emitted[point.Payload.SourceID] = true
			result.Items = append(result.Items, item)
			if len(result.Items) == int(limit) {
				break
			}
		}
	}
	return result, nil
}
