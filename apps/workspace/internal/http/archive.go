package http

import (
	"bytes"
	"encoding/json"

	"github.com/gin-gonic/gin"
)

func (s *Server) archive(c *gin.Context) {
	w, r := c.Writer, c.Request
	ws, err := resourceID(c, "ws")
	if err != nil {
		failure(w, r, err)
		return
	}
	if _, err = s.Store.Authorize(r.Context(), ws, actorID(r), "viewer"); err != nil {
		failure(w, r, err)
		return
	}
	node, err := resourceID(c, "node")
	if err != nil {
		failure(w, r, err)
		return
	}
	storage, err := s.Store.Storage(r.Context(), ws)
	if err != nil {
		failure(w, r, err)
		return
	}
	body, err := json.Marshal(map[string]any{"scope": map[string]any{"actor_id": actorID(r), "mounts": []any{map[string]any{"path": "/drive", "filesystem_id": storage.FilesystemID}}}})
	if err != nil {
		failure(w, r, err)
		return
	}
	s.proxyLetfs(c, "POST", "/internal/v1/filesystems/"+storage.FilesystemID.String()+"/nodes/"+node.String()+"/archive", bytes.NewReader(body))
}
