package http

import (
	"github.com/gin-gonic/gin"
	"net/http"

	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
)

func (s *Server) members(c *gin.Context) {
	w, r := c.Writer, c.Request
	ws, e := resourceID(c, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	scope := "members/" + ws.String()
	after, limit, e := page(r, scope)
	if e != nil {
		failure(w, r, e)
		return
	}
	items, nextID, e := s.Service.Members(r.Context(), ws, actorID(r), after, limit)
	if e != nil {
		failure(w, r, e)
		return
	}
	var next *string
	if nextID != nil {
		next = cursor(scope, *nextID)
	}
	respond(w, 200, map[string]any{"items": items, "next_cursor": next})
}
func (s *Server) changeMember(c *gin.Context) {
	w, r := c.Writer, c.Request
	ws, e := resourceID(c, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	target, e := resourceID(c, "user")
	if e != nil {
		failure(w, r, e)
		return
	}
	var in struct {
		Role string `json:"role"`
	}
	remove := r.Method == http.MethodDelete
	if !remove {
		if e = decode(w, r, &in); e != nil {
			failure(w, r, e)
			return
		}
	}
	revision, e := precondition(r)
	if e != nil {
		failure(w, r, e)
		return
	}
	if e = s.Service.ChangeMember(r.Context(), ws, actorID(r), target, revision, in.Role, remove); e != nil {
		failure(w, r, e)
		return
	}
	w.WriteHeader(204)
}
func (s *Server) invite(c *gin.Context) {
	w, r := c.Writer, c.Request
	ws, e := resourceID(c, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	var in struct {
		Email string `json:"email"`
		Role  string `json:"role"`
	}
	if e = decode(w, r, &in); e != nil {
		failure(w, r, e)
		return
	}
	v, token, e := s.Service.Invite(r.Context(), ws, actorID(r), in.Email, in.Role)
	if e != nil {
		failure(w, r, e)
		return
	}
	status := http.StatusCreated
	if token == "" {
		status = http.StatusOK
	}
	w.Header().Set("Location", "/v1/workspaces/"+ws.String()+"/invitations/"+v.ID.String())
	respond(w, status, struct {
		workspace.Invitation
		Token string `json:"token,omitempty"`
	}{Invitation: v, Token: token})
}
func (s *Server) invitations(c *gin.Context) {
	w, r := c.Writer, c.Request
	ws, e := resourceID(c, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	scope := "invitations/" + ws.String()
	after, limit, e := page(r, scope)
	if e != nil {
		failure(w, r, e)
		return
	}
	items, nextID, e := s.Service.Invitations(r.Context(), ws, actorID(r), after, limit)
	if e != nil {
		failure(w, r, e)
		return
	}
	var next *string
	if nextID != nil {
		next = cursor(scope, *nextID)
	}
	respond(w, 200, map[string]any{"items": items, "next_cursor": next})
}
func (s *Server) revokeInvitation(c *gin.Context) {
	w, r := c.Writer, c.Request
	ws, e := resourceID(c, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	id, e := resourceID(c, "invitation")
	if e != nil {
		failure(w, r, e)
		return
	}
	if e = s.Service.RevokeInvitation(r.Context(), ws, actorID(r), id); e != nil {
		failure(w, r, e)
		return
	}
	w.WriteHeader(204)
}
func (s *Server) acceptInvitation(c *gin.Context) {
	w, r := c.Writer, c.Request
	var in struct {
		Token string `json:"token"`
	}
	if e := decode(w, r, &in); e != nil {
		failure(w, r, e)
		return
	}
	value, e := s.Service.AcceptInvitation(r.Context(), actorID(r), in.Token)
	if e != nil {
		failure(w, r, e)
		return
	}
	w.Header().Set("Location", "/v1/workspaces/"+value.WorkspaceID.String()+"/members/"+actorID(r).String())
	respond(w, 201, value)
}
