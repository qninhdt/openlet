package http

import (
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/qninhdt/openlet/packages/go/identity"
)

func (s *Server) accessibleScopes(c *gin.Context) {
	ws, err := resourceID(c, "ws")
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	query := c.Request.URL.Query()
	for key, values := range query {
		if len(values) != 1 || (key != "leta_id" && key != "cursor" && key != "limit") {
			failure(c.Writer, c.Request, workspace.Fault{Code: "VALIDATION"})
			return
		}
	}
	limit, err := pageLimit(c.Request)
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	actor := actorID(c.Request)
	subject := identity.Actor{Kind: identity.User, ID: actor}
	if value, supplied := query["leta_id"]; supplied {
		id, err := uuid.Parse(value[0])
		if err != nil || id == uuid.Nil {
			failure(c.Writer, c.Request, workspace.Fault{Code: "VALIDATION"})
			return
		}
		subject = identity.Actor{Kind: identity.Leta, ID: id}
	}
	var cursor *string
	if value, supplied := query["cursor"]; supplied {
		cursor = &value[0]
	}
	page, err := s.Service.AccessibleScopes(c.Request.Context(), ws, subject, actor, cursor, int32(limit))
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	respond(c.Writer, 200, page)
}
