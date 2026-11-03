package httpapi

import (
	"encoding/json"
	"net/http"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func searchFilters(value filesystem.SearchFilters) (*letfsv1.SearchFilters, error) {
	result := &letfsv1.SearchFilters{SemanticType: value.SemanticType, MediaType: value.MediaType}
	if value.Parent != nil {
		parent, err := locatorMessage(*value.Parent)
		if err != nil {
			return nil, err
		}
		result.Parent = parent
	}
	if value.CreatedAfter != nil {
		result.CreatedAfter = timestamppb.New(*value.CreatedAfter)
	}
	if value.CreatedBefore != nil {
		result.CreatedBefore = timestamppb.New(*value.CreatedBefore)
	}
	if value.UpdatedAfter != nil {
		result.UpdatedAfter = timestamppb.New(*value.UpdatedAfter)
	}
	if value.UpdatedBefore != nil {
		result.UpdatedBefore = timestamppb.New(*value.UpdatedBefore)
	}
	return result, nil
}
func (s *Server) searchFiles(w http.ResponseWriter, r *http.Request) error {
	q := r.URL.Query()
	allowed := map[string]bool{"q": true, "limit": true, "cursor": true, "sort": true, "direction": true, "type": true, "media_type": true, "created_after": true, "created_before": true, "updated_after": true, "updated_before": true, "node_id": true, "path": true, "cwd_id": true, "mount_path": true, "expected_node_id": true, "expected_parent_id": true}
	for key, values := range q {
		if !allowed[key] || len(values) != 1 {
			return invalid()
		}
	}
	limit, cursor, err := pageInput(r)
	if err != nil {
		return err
	}
	request := &letfsv1.SearchFilesRequest{FilesystemId: fsID(r), PathContext: pathContext(r), Query: q.Get("q"), Limit: limit, Cursor: cursor, Filters: &letfsv1.SearchFilters{}}
	if q.Has("sort") {
		v := q.Get("sort")
		request.Sort = &v
	}
	if q.Has("direction") {
		v := q.Get("direction")
		request.Direction = &v
	}
	if q.Has("type") {
		v := q.Get("type")
		request.Filters.SemanticType = &v
	}
	if q.Has("media_type") {
		v := q.Get("media_type")
		request.Filters.MediaType = &v
	}
	for key, target := range map[string]**timestamppb.Timestamp{"created_after": &request.Filters.CreatedAfter, "created_before": &request.Filters.CreatedBefore, "updated_after": &request.Filters.UpdatedAfter, "updated_before": &request.Filters.UpdatedBefore} {
		if q.Has(key) {
			value := &timestamppb.Timestamp{}
			data, _ := json.Marshal(q.Get(key))
			if protojson.Unmarshal(data, value) != nil {
				return invalid()
			}
			*target = value
		}
	}
	if q.Has("node_id") || q.Has("path") || q.Has("cwd_id") {
		request.Filters.Parent, err = queryLocator(r)
		if err != nil {
			return err
		}
	}
	result, err := s.API.SearchFiles(r.Context(), request)
	if err != nil {
		return err
	}
	return writeSearch(w, r, result.Items, result.NextCursor, result.Degraded, result.DegradedReason)
}
func (s *Server) semanticSearch(w http.ResponseWriter, r *http.Request) error {
	var input filesystem.SearchInput
	if err := decodeJSON(w, r, &input); err != nil {
		return err
	}
	if input.Sort != nil || input.Direction != nil {
		return invalid()
	}
	filters, err := searchFilters(input.Filters)
	if err != nil {
		return err
	}
	result, err := s.API.SemanticSearch(r.Context(), &letfsv1.SemanticSearchRequest{FilesystemId: fsID(r), PathContext: pathContext(r), Query: input.Query, Limit: input.Limit, Cursor: input.Cursor, Filters: filters})
	if err != nil {
		return err
	}
	return writeSearch(w, r, result.Items, result.NextCursor, result.Degraded, result.DegradedReason)
}

type searchTimestamp struct{ *timestamppb.Timestamp }

func (value searchTimestamp) MarshalJSON() ([]byte, error) {
	return protojson.Marshal(value.Timestamp)
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
	NodeID       string           `json:"node_id"`
	FilesystemID string           `json:"filesystem_id,omitempty"`
	ParentID     *string          `json:"parent_id,omitempty"`
	Name         string           `json:"name,omitempty"`
	Kind         string           `json:"kind,omitempty"`
	Revision     int64            `json:"revision,string,omitempty"`
	SizeBytes    int64            `json:"size_bytes,string,omitempty"`
	MediaType    *string          `json:"media_type,omitempty"`
	CreatedAt    *searchTimestamp `json:"created_at,omitempty"`
	UpdatedAt    *searchTimestamp `json:"updated_at,omitempty"`
	Title        *string          `json:"title,omitempty"`
	Description  *string          `json:"description,omitempty"`
	SemanticType *string          `json:"semantic_type,omitempty"`
	Context      *string          `json:"context,omitempty"`
	Path         string           `json:"path"`
	Matched      *searchMatch     `json:"matched,omitempty"`
}

func writeSearch(w http.ResponseWriter, r *http.Request, items []*letfsv1.SearchResult, cursor *string, degraded bool, reason *string) error {
	rows := make([]searchResult, 0, len(items))
	for _, item := range items {
		node := item.Node
		row := searchResult{
			NodeID: node.Id, FilesystemID: node.FilesystemId, ParentID: node.ParentId,
			Name: node.Name, Kind: node.Kind, Revision: node.Revision, SizeBytes: node.SizeBytes,
			MediaType: node.MediaType, Title: node.Title, Description: node.Description,
			SemanticType: node.SemanticType, Context: node.Context, Path: item.Path,
		}
		if node.CreatedAt != nil {
			row.CreatedAt = &searchTimestamp{node.CreatedAt}
		}
		if node.UpdatedAt != nil {
			row.UpdatedAt = &searchTimestamp{node.UpdatedAt}
		}
		if item.Matched != nil {
			row.Matched = &searchMatch{FileID: item.Matched.FileId, Snippet: item.Matched.Snippet}
			for _, part := range item.Matched.Breadcrumb {
				row.Matched.Breadcrumb = append(row.Matched.Breadcrumb, searchBreadcrumb{NodeID: part.NodeId, Filename: part.Filename})
			}
		}
		rows = append(rows, row)
	}
	result := struct {
		Items          []searchResult `json:"items"`
		NextCursor     *string        `json:"next_cursor"`
		Degraded       bool           `json:"degraded"`
		DegradedReason *string        `json:"degraded_reason,omitempty"`
	}{rows, cursor, degraded, reason}
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
