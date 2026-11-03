package http

import (
	"context"
	"github.com/gin-gonic/gin"
	worker "github.com/qninhdt/openlet/apps/workspace/internal/temporal"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"log/slog"
	"time"
)

func (s *Server) deleteWorkspace(c *gin.Context) {
	w, r := c.Writer, c.Request
	id, err := resourceID(c, "ws")
	if err != nil {
		failure(w, r, err)
		return
	}
	revision, err := precondition(r)
	if err != nil {
		failure(w, r, err)
		return
	}
	value, err := s.Store.BeginDeletion(r.Context(), workspace.DeleteInput{ActorID: actorID(r), WorkspaceID: id, Revision: revision})
	if err != nil {
		failure(w, r, err)
		return
	}
	if value.Status == "deleted" {
		w.WriteHeader(204)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	if err = worker.StartDelete(ctx, s.Temporal, s.Store, id); err != nil {
		slog.WarnContext(r.Context(), "workspace deletion dispatch deferred", "workspace_id", id, "reason", err.Error())
	}
	w.Header().Set("Location", "/v1/workspaces/"+id.String())
	w.Header().Set("ETag", "\""+value.Revision+"\"")
	respond(w, 202, value)
}
