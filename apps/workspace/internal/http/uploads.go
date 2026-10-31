package http

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"openlet/apps/workspace/internal/workspace"
)

type uploadReceipt struct {
	PartNumber uint32 `json:"part_number"`
	ETag       string `json:"etag"`
}

func (s *Server) createUpload(c *gin.Context) {
	fs, ok := s.nodeFilesystem(c, "editor")
	if !ok {
		return
	}
	w, r := c.Writer, c.Request
	var input struct {
		ParentID   *uuid.UUID `json:"parent_id,omitempty"`
		NodeID     *uuid.UUID `json:"node_id,omitempty"`
		Name       *string    `json:"name,omitempty"`
		MediaType  string     `json:"media_type"`
		SizeBytes  string     `json:"size_bytes"`
		ContentMD5 *string    `json:"content_md5,omitempty"`
	}
	if err := decode(w, r, &input); err != nil {
		failure(w, r, err)
		return
	}
	key, err := uuid.Parse(r.Header.Get("Idempotency-Key"))
	if err != nil || key == uuid.Nil || len(r.Header.Values("Idempotency-Key")) != 1 ||
		(input.NodeID == nil) == (input.ParentID == nil) ||
		(input.NodeID != nil && (*input.NodeID == uuid.Nil || input.Name != nil)) ||
		(input.ParentID != nil && (*input.ParentID == uuid.Nil || input.Name == nil)) {
		failure(w, r, workspace.Fault{Code: "VALIDATION"})
		return
	}
	body := map[string]any{"storage": "object", "size_bytes": input.SizeBytes, "media_type": input.MediaType, "content_md5": input.ContentMD5, "request_key": key}
	if input.NodeID != nil {
		revision, err := precondition(r)
		if err != nil {
			failure(w, r, err)
			return
		}
		body["locator"] = locator{NodeID: input.NodeID}
		body["revision"] = revision
	} else {
		if r.Header.Get("If-Match") != "" {
			failure(w, r, workspace.Fault{Code: "VALIDATION"})
			return
		}
		body["parent"] = locator{NodeID: input.ParentID}
		body["name"] = *input.Name
	}
	data, err := json.Marshal(map[string]any{"scope": map[string]any{"actor_id": actorID(r), "mounts": []any{map[string]any{"path": "/drive", "filesystem_id": fs}}}, "input": body})
	if err != nil {
		failure(w, r, err)
		return
	}
	s.proxyLetfs(c, http.MethodPost, "/internal/v1/filesystems/"+fs.String()+"/uploads", bytes.NewReader(data))
}

func (s *Server) uploadResource(action string) gin.HandlerFunc {
	return func(c *gin.Context) {
		fs, ok := s.nodeFilesystem(c, "editor")
		if !ok {
			return
		}
		id, err := resourceID(c, "upload")
		if err != nil {
			failure(c.Writer, c.Request, err)
			return
		}
		path := "/internal/v1/filesystems/" + fs.String() + "/uploads/" + id.String()
		var body io.Reader
		switch action {
		case "complete":
			var input struct {
				Parts []uploadReceipt `json:"parts,omitempty"`
			}
			if err := decodeLimited(c.Writer, c.Request, &input, 2*1048576); err != nil {
				failure(c.Writer, c.Request, err)
				return
			}
			data, err := json.Marshal(input)
			if err != nil {
				failure(c.Writer, c.Request, err)
				return
			}
			body = bytes.NewReader(data)
			path += "/completion"
		case "parts":
			path += "/parts"
			if c.Request.URL.RawQuery != "" {
				path += "?" + c.Request.URL.RawQuery
			}
		}
		s.proxyLetfs(c, c.Request.Method, path, body)
	}
}
