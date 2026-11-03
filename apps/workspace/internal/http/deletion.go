package http

import (
	"github.com/gin-gonic/gin"
	worker "github.com/qninhdt/openlet/apps/workspace/internal/temporal"
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
	value, err := worker.Mutate(r.Context(), s.Temporal, worker.Mutation{Kind: "delete", WorkspaceID: id, ActorID: actorID(r), Revision: revision})
	if err != nil {
		failure(w, r, err)
		return
	}
	if value.Status == "deleted" {
		w.WriteHeader(204)
		return
	}
	w.Header().Set("Location", "/v1/workspaces/"+id.String())
	w.Header().Set("ETag", "\""+value.Revision+"\"")
	respond(w, 202, value)
}
