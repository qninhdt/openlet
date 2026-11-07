package http

import "github.com/gin-gonic/gin"

func (s *Server) deleteWorkspace(c *gin.Context) {
	w, r := c.Writer, c.Request
	id, err := resourceID(c, "ws")
	if err != nil {
		failure(w, r, err)
		return
	}
	value, err := s.Service.Delete(r.Context(), id, actorID(r))
	if err != nil {
		failure(w, r, err)
		return
	}
	if value.Status == "deleted" {
		w.WriteHeader(204)
		return
	}
	w.Header().Set("Location", "/v1/workspaces/"+id.String())
	respond(w, 202, value)
}
