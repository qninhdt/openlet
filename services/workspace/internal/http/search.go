package http

import (
	"bytes"
	"encoding/json"
	"net/http"
	"openlet/services/workspace/internal/workspace"
)

type searchFilters struct {
	Parent        *locator `json:"parent,omitempty"`
	Type          string   `json:"type,omitempty"`
	MediaType     string   `json:"media_type,omitempty"`
	CreatedAfter  string   `json:"created_after,omitempty"`
	CreatedBefore string   `json:"created_before,omitempty"`
	UpdatedAfter  string   `json:"updated_after,omitempty"`
	UpdatedBefore string   `json:"updated_before,omitempty"`
}
type searchInput struct {
	Query     string        `json:"query"`
	Filters   searchFilters `json:"filters"`
	Limit     *int          `json:"limit,omitempty"`
	Cursor    string        `json:"cursor,omitempty"`
	Sort      string        `json:"sort,omitempty"`
	Direction string        `json:"direction,omitempty"`
}

func (s *Server) searchFiles(w http.ResponseWriter, r *http.Request) {
	ws, err := resourceID(r, "ws")
	if err != nil {
		failure(w, r, err)
		return
	}
	if _, err = s.Store.Authorize(r.Context(), ws, actorID(r), "viewer"); err != nil {
		failure(w, r, err)
		return
	}
	mapping, err := s.Store.Storage(r.Context(), ws)
	if err != nil {
		failure(w, r, err)
		return
	}
	var in searchInput
	action := "semantic-search"
	if r.Method == "GET" {
		action = "search"
		q := r.URL.Query()
		allowed := map[string]bool{"query": true, "limit": true, "cursor": true, "sort": true, "direction": true, "type": true, "media_type": true, "created_after": true, "created_before": true, "updated_after": true, "updated_before": true, "node_id": true, "path": true, "cwd_id": true}
		for key, values := range q {
			if !allowed[key] || len(values) != 1 {
				failure(w, r, workspace.Fault{Code: "VALIDATION"})
				return
			}
		}
		limit, err := pageLimit(r)
		if err != nil {
			failure(w, r, err)
			return
		}
		in.Query = q.Get("query")
		in.Limit = &limit
		in.Cursor = q.Get("cursor")
		in.Sort = q.Get("sort")
		in.Direction = q.Get("direction")
		in.Filters = searchFilters{Type: q.Get("type"), MediaType: q.Get("media_type"), CreatedAfter: q.Get("created_after"), CreatedBefore: q.Get("created_before"), UpdatedAfter: q.Get("updated_after"), UpdatedBefore: q.Get("updated_before")}
		if q.Has("node_id") || q.Has("path") || q.Has("cwd_id") {
			in.Filters.Parent, err = queryLocator(r)
			if err != nil {
				failure(w, r, err)
				return
			}
		}
	} else if err = decode(w, r, &in); err != nil {
		failure(w, r, err)
		return
	}
	body, err := json.Marshal(map[string]any{"scope": map[string]any{"actor_id": actorID(r), "mounts": []any{map[string]any{"path": "/drive", "filesystem_id": mapping.FilesystemID}}}, "input": in})
	if err != nil {
		failure(w, r, err)
		return
	}
	s.proxyLetfs(w, r, "POST", "/internal/v1/filesystems/"+mapping.FilesystemID.String()+"/files/"+action, bytes.NewReader(body))
}
