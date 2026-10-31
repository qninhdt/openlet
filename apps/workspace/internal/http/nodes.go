package http

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"openlet/apps/workspace/internal/workspace"
)

type nodeCreate struct {
	Kind          string     `json:"kind"`
	ParentID      uuid.UUID  `json:"parent_id"`
	Name          string     `json:"name"`
	ContentBase64 *string    `json:"content_base64,omitempty"`
	MediaType     *string    `json:"media_type,omitempty"`
	SourceID      *uuid.UUID `json:"source_id,omitempty"`
}

func (s *Server) nodeFilesystem(c *gin.Context, role string) (uuid.UUID, bool) {
	w, r := c.Writer, c.Request
	ws, err := resourceID(c, "ws")
	if err != nil {
		failure(w, r, err)
		return uuid.Nil, false
	}
	if _, err = s.Store.Authorize(r.Context(), ws, actorID(r), role); err != nil {
		failure(w, r, err)
		return uuid.Nil, false
	}
	storage, err := s.Store.Storage(r.Context(), ws)
	if err != nil {
		failure(w, r, err)
		return uuid.Nil, false
	}
	return storage.FilesystemID, true
}
func (s *Server) createNode(c *gin.Context) {
	fs, ok := s.nodeFilesystem(c, "editor")
	if !ok {
		return
	}
	w, r := c.Writer, c.Request
	var input nodeCreate
	if err := decodeLimited(w, r, &input, 2*1048576); err != nil {
		failure(w, r, err)
		return
	}
	key, err := uuid.Parse(r.Header.Get("Idempotency-Key"))
	if err != nil || key == uuid.Nil || len(r.Header.Values("Idempotency-Key")) != 1 || input.ParentID == uuid.Nil {
		failure(w, r, workspace.Fault{Code: "VALIDATION"})
		return
	}
	if input.SourceID != nil {
		if *input.SourceID == uuid.Nil || input.Kind != "" || input.ContentBase64 != nil || input.MediaType != nil {
			failure(w, r, workspace.Fault{Code: "VALIDATION"})
			return
		}
		revision, err := precondition(r)
		if err != nil {
			failure(w, r, err)
			return
		}
		body, err := json.Marshal(map[string]any{"scope": map[string]any{"actor_id": actorID(r), "mounts": []any{map[string]any{"path": "/drive", "filesystem_id": fs}}}, "input": map[string]any{"source_id": *input.SourceID, "parent_id": input.ParentID, "name": input.Name, "revision": revision, "request_key": key}})
		if err != nil {
			failure(w, r, err)
			return
		}
		s.proxyLetfs(c, http.MethodPost, "/internal/v1/filesystems/"+fs.String()+"/nodes", bytes.NewReader(body))
		return
	}
	body := map[string]any{"kind": input.Kind, "parent": locator{NodeID: &input.ParentID}, "name": input.Name, "request_key": key}
	if input.ContentBase64 != nil {
		body["content_base64"] = *input.ContentBase64
	}
	if input.MediaType != nil {
		body["media_type"] = *input.MediaType
	}
	data, err := json.Marshal(map[string]any{"scope": map[string]any{"actor_id": actorID(r), "mounts": []any{map[string]any{"path": "/drive", "filesystem_id": fs}}}, "input": body})
	if err != nil {
		failure(w, r, err)
		return
	}
	s.proxyLetfs(c, http.MethodPost, "/internal/v1/filesystems/"+fs.String()+"/nodes", bytes.NewReader(data))
}
func (s *Server) readNode(action string) gin.HandlerFunc {
	return func(c *gin.Context) {
		fs, ok := s.nodeFilesystem(c, "viewer")
		if !ok {
			return
		}
		path := "/internal/v1/filesystems/" + fs.String() + "/nodes"
		if c.Param("node") != "" {
			node, err := resourceID(c, "node")
			if err != nil {
				failure(c.Writer, c.Request, err)
				return
			}
			path += "/" + node.String()
			if action == "content" || action == "processing" {
				path += "/" + action
			}
		} else if action == "resolve" {
			path += "/resolve"
		}
		if c.Request.URL.RawQuery != "" {
			path += "?" + c.Request.URL.RawQuery
		}
		s.proxyLetfs(c, http.MethodGet, path, nil)
	}
}

func (s *Server) updateNode(c *gin.Context) {
	fs, ok := s.nodeFilesystem(c, "editor")
	if !ok {
		return
	}
	w, r := c.Writer, c.Request
	node, err := resourceID(c, "node")
	if err != nil {
		failure(w, r, err)
		return
	}
	if _, err = precondition(r); err != nil {
		failure(w, r, err)
		return
	}
	path := "/internal/v1/filesystems/" + fs.String() + "/nodes/" + node.String()
	if r.Method == http.MethodPatch {
		var input struct {
			Name     *string    `json:"name,omitempty"`
			ParentID *uuid.UUID `json:"parent_id,omitempty"`
		}
		if err = decode(w, r, &input); err != nil {
			failure(w, r, err)
			return
		}
		data, err := json.Marshal(input)
		if err != nil {
			failure(w, r, err)
			return
		}
		s.proxyLetfs(c, http.MethodPatch, path, bytes.NewReader(data))
		return
	}
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 1048576))
	if err != nil {
		var oversized *http.MaxBytesError
		if errors.As(err, &oversized) {
			Error(w, r, 413, "REQUEST_LIMIT", "inline content exceeds limit")
		} else {
			Error(w, r, 400, "VALIDATION", "incomplete request body")
		}
		return
	}
	s.proxyLetfs(c, http.MethodPut, path+"/content", bytes.NewReader(body))
}

func (s *Server) reprocessNode(c *gin.Context) {
	fs, ok := s.nodeFilesystem(c, "editor")
	if !ok {
		return
	}
	w, r := c.Writer, c.Request
	node, err := resourceID(c, "node")
	if err != nil {
		failure(w, r, err)
		return
	}
	var input struct{}
	if err = decode(w, r, &input); err != nil {
		failure(w, r, err)
		return
	}
	key, err := uuid.Parse(r.Header.Get("Idempotency-Key"))
	if err != nil || key == uuid.Nil || len(r.Header.Values("Idempotency-Key")) != 1 {
		failure(w, r, workspace.Fault{Code: "VALIDATION"})
		return
	}
	s.proxyLetfs(c, http.MethodPost, "/internal/v1/filesystems/"+fs.String()+"/nodes/"+node.String()+"/processing-runs", bytes.NewBufferString("{}"))
}

func (s *Server) copyStatus(c *gin.Context) {
	ws, err := resourceID(c, "ws")
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	member, err := s.Store.Authorize(c.Request.Context(), ws, actorID(c.Request), "viewer")
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	storage, err := s.Store.Storage(c.Request.Context(), ws)
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	id, err := resourceID(c, "copy")
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	c.Set("workspace-role", member.Role)
	s.proxyLetfs(c, http.MethodGet, "/internal/v1/filesystems/"+storage.FilesystemID.String()+"/copies/"+id.String(), nil)
}
