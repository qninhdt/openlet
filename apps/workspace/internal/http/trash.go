package http

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"openlet/apps/workspace/internal/workspace"
)

func (s *Server) trashNode(c *gin.Context) {
	fs, ok := s.nodeFilesystem(c, "editor")
	if !ok {
		return
	}
	node, err := resourceID(c, "node")
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	if _, err = precondition(c.Request); err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	s.proxyLetfs(c, http.MethodDelete, "/internal/v1/filesystems/"+fs.String()+"/nodes/"+node.String(), nil)
}

func (s *Server) trashResource(c *gin.Context) {
	role := "viewer"
	if c.Request.Method == http.MethodPost {
		role = "editor"
	}
	if c.Request.Method == http.MethodDelete {
		role = "owner"
	}
	fs, ok := s.nodeFilesystem(c, role)
	if !ok {
		return
	}
	path := "/internal/v1/filesystems/" + fs.String() + "/trash-entries"
	raw := c.Param("entry")
	if raw != "" {
		if c.Request.Method == http.MethodPost {
			if !strings.HasSuffix(raw, ":restore") {
				failure(c.Writer, c.Request, workspace.Fault{Code: "NOT_FOUND"})
				return
			}
			raw = strings.TrimSuffix(raw, ":restore")
		}
		id, err := uuid.Parse(raw)
		if err != nil || id == uuid.Nil {
			failure(c.Writer, c.Request, workspace.Fault{Code: "VALIDATION"})
			return
		}
		path += "/" + id.String()
		if c.Request.Method == http.MethodPost {
			path += "/restore"
		}
	}
	if c.Request.URL.RawQuery != "" {
		path += "?" + c.Request.URL.RawQuery
	}
	s.proxyLetfs(c, c.Request.Method, path, nil)
}
