package httpapi

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
)

func searchTime(value string) (*time.Time, error) {
	parsed, err := time.Parse(time.RFC3339Nano, value)
	if err != nil || parsed.Year() < 1 || parsed.Year() > 9999 {
		return nil, invalid()
	}
	return &parsed, nil
}

func (s *Server) searchFiles(w http.ResponseWriter, r *http.Request) error {
	q := r.URL.Query()
	allowed := map[string]bool{"q": true, "limit": true, "cursor": true, "sort": true, "direction": true, "type": true, "media_type": true, "created_after": true, "created_before": true, "updated_after": true, "updated_before": true, "node_id": true, "path": true, "cwd_id": true, "expected_node_id": true, "expected_parent_id": true}
	for key, values := range q {
		if !allowed[key] || len(values) != 1 {
			return invalid()
		}
	}
	limit, cursor, err := pageInput(r)
	if err != nil {
		return err
	}
	input := filesystem.SearchInput{Query: q.Get("q"), Limit: limit, Cursor: cursor}
	if q.Has("sort") {
		value := q.Get("sort")
		input.Sort = &value
	}
	if q.Has("direction") {
		value := q.Get("direction")
		input.Direction = &value
	}
	if q.Has("type") {
		value := q.Get("type")
		input.Filters.SemanticType = &value
	}
	if q.Has("media_type") {
		value := q.Get("media_type")
		input.Filters.MediaType = &value
	}
	for _, field := range []struct {
		key    string
		target **time.Time
	}{{"created_after", &input.Filters.CreatedAfter}, {"created_before", &input.Filters.CreatedBefore}, {"updated_after", &input.Filters.UpdatedAfter}, {"updated_before", &input.Filters.UpdatedBefore}} {
		if q.Has(field.key) {
			value, err := searchTime(q.Get(field.key))
			if err != nil {
				return err
			}
			*field.target = value
		}
	}
	if q.Has("node_id") || q.Has("path") || q.Has("cwd_id") {
		parent, err := queryLocator(r)
		if err != nil {
			return err
		}
		input.Filters.Parent = &parent
	}
	fs, err := s.requestContext(r)
	if err != nil {
		return err
	}
	page, err := s.Store.SearchFiles(r.Context(), fs, input)
	if err != nil {
		return err
	}
	return writeSearch(w, r, page)
}

func (s *Server) semanticSearch(w http.ResponseWriter, r *http.Request) error {
	var input filesystem.SemanticSearchInput
	if err := decodeJSON(w, r, &input); err != nil {
		return err
	}
	fs, err := s.requestContext(r)
	if err != nil {
		return err
	}
	page, err := s.Store.SemanticSearch(r.Context(), fs, input)
	if err != nil {
		return err
	}
	return writeSearchJSON(w, searchResponse{Items: searchRows(page.Items), Degraded: page.Degraded, DegradedReason: page.DegradedReason})
}

type searchBreadcrumb struct {
	NodeID   string `json:"node_id,omitempty"`
	Filename string `json:"filename,omitempty"`
}
type searchMatch struct {
	FileID     string             `json:"file_id,omitempty"`
	Breadcrumb []searchBreadcrumb `json:"breadcrumb,omitempty"`
	Snippet    string             `json:"snippet,omitempty"`
}
type searchResult struct {
	NodeID       string       `json:"node_id"`
	FilesystemID string       `json:"filesystem_id,omitempty"`
	ParentID     *string      `json:"parent_id,omitempty"`
	Name         string       `json:"name,omitempty"`
	Kind         string       `json:"kind,omitempty"`
	Revision     int64        `json:"revision,string,omitempty"`
	SizeBytes    int64        `json:"size_bytes,string,omitempty"`
	MediaType    *string      `json:"media_type,omitempty"`
	CreatedAt    *timestamp   `json:"created_at,omitempty"`
	UpdatedAt    *timestamp   `json:"updated_at,omitempty"`
	Title        *string      `json:"title,omitempty"`
	Description  *string      `json:"description,omitempty"`
	SemanticType *string      `json:"semantic_type,omitempty"`
	Context      *string      `json:"context,omitempty"`
	Path         string       `json:"path"`
	Matched      *searchMatch `json:"matched,omitempty"`
}

func searchRows(items []filesystem.SearchResult) []searchResult {
	rows := make([]searchResult, 0, len(items))
	for _, item := range items {
		node := item.Node
		var parent *string
		if node.ParentID != nil {
			value := node.ParentID.String()
			parent = &value
		}
		row := searchResult{NodeID: node.ID.String(), ParentID: parent, Name: node.Name, Kind: node.Kind, Revision: node.Revision, SizeBytes: node.SizeBytes, MediaType: node.MediaType, Title: node.Title, Description: node.Description, SemanticType: node.SemanticType, Context: node.Context, Path: item.Path}
		if node.ScopeID != uuid.Nil {
			row.FilesystemID = node.ScopeID.String()
		}
		if !node.CreatedAt.IsZero() {
			row.CreatedAt = &timestamp{node.CreatedAt}
		}
		if !node.UpdatedAt.IsZero() {
			row.UpdatedAt = &timestamp{node.UpdatedAt}
		}
		if item.Matched != nil {
			row.Matched = &searchMatch{FileID: item.Matched.FileID.String(), Snippet: item.Matched.Snippet}
			for _, part := range item.Matched.Breadcrumb {
				row.Matched.Breadcrumb = append(row.Matched.Breadcrumb, searchBreadcrumb{part.NodeID.String(), part.Filename})
			}
		}
		rows = append(rows, row)
	}
	return rows
}

type searchResponse struct {
	Items          []searchResult `json:"items"`
	Degraded       bool           `json:"degraded"`
	DegradedReason *string        `json:"degraded_reason,omitempty"`
}

func writeSearch(w http.ResponseWriter, r *http.Request, page filesystem.SearchPage) error {
	return writeSearchJSON(w, struct {
		searchResponse
		NextCursor *string `json:"next_cursor"`
	}{searchResponse{searchRows(page.Items), page.Degraded, page.DegradedReason}, page.NextCursor})
}

func writeSearchJSON(w http.ResponseWriter, result any) error {
	data, err := json.Marshal(result)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	if _, err = w.Write(data); err != nil {
		panic(http.ErrAbortHandler)
	}
	return nil
}
