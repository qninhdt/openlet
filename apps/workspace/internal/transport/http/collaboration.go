package http

import (
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"net/http"

	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/qninhdt/openlet/packages/go/identity"
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
	if e = s.Service.ChangeMember(r.Context(), ws, actorID(r), target, in.Role, remove); e != nil {
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

func (s *Server) addMember(c *gin.Context) {
	ws, err := resourceID(c, "ws")
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	var in struct {
		UserID uuid.UUID `json:"user_id"`
		Role   string    `json:"role"`
	}
	if err = decode(c.Writer, c.Request, &in); err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	value, err := s.Service.AddUser(c.Request.Context(), ws, actorID(c.Request), in.UserID, in.Role)
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	respond(c.Writer, 201, value)
}
func (s *Server) scopeAccess(c *gin.Context) {
	ws, err := resourceID(c, "ws")
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	scope, err := resourceID(c, "scope")
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	target, err := resourceID(c, "user")
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	var in struct {
		Role        string             `json:"role"`
		GranteeKind identity.ActorKind `json:"grantee_kind"`
	}
	if err = decode(c.Writer, c.Request, &in); err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	if in.GranteeKind == "" {
		in.GranteeKind = identity.User
	}
	if in.GranteeKind != identity.User && in.GranteeKind != identity.Leta {
		failure(c.Writer, c.Request, workspace.Fault{Code: "VALIDATION"})
		return
	}
	_, err = s.Service.ChangeTypedScopeAccess(c.Request.Context(), workspace.Mutation{
		Kind: "scope", WorkspaceID: ws, ActorID: actorID(c.Request), ScopeID: scope,
		TargetID: target, TargetKind: in.GranteeKind, ScopeRole: in.Role, Revoke: c.Request.Method == http.MethodDelete,
	})
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	c.Status(204)
}
