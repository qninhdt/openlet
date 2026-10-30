package http

import (
	"bytes"
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"openlet/services/workspace/internal/workspace"
)

type exportSelection struct {
	Locators  []locator `json:"locators"`
	Artifacts bool      `json:"artifacts"`
}

func (s *Server) exportFiles(w http.ResponseWriter, r *http.Request) {
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
	scope := map[string]any{"actor_id": actorID(r), "mounts": []any{map[string]any{"path": "/drive", "filesystem_id": mapping.FilesystemID}}}
	path := "/internal/v1/filesystems/" + mapping.FilesystemID.String() + "/exports"
	body := map[string]any{"scope": scope}
	if r.Method == "POST" {
		var in exportSelection
		if err = decode(w, r, &in); err != nil {
			failure(w, r, err)
			return
		}
		key, err := uuid.Parse(r.Header.Get("Idempotency-Key"))
		if err != nil || key == uuid.Nil {
			failure(w, r, workspace.Fault{Code: "VALIDATION"})
			return
		}
		body["input"] = map[string]any{"locators": in.Locators, "artifacts": in.Artifacts, "request_key": key}
	} else {
		id, err := resourceID(r, "export")
		if err != nil {
			failure(w, r, err)
			return
		}
		action := "status"
		if chi.URLParam(r, "action") == "download" {
			action = "download"
		}
		path += "/" + id.String() + "/" + action
	}
	data, err := json.Marshal(body)
	if err != nil {
		failure(w, r, err)
		return
	}
	s.proxyLetfs(w, r, "POST", path, bytes.NewReader(data))
}
