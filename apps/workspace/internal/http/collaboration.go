package http

import (
	"crypto/sha256"
	"github.com/gin-gonic/gin"
	"net/http"

	"github.com/google/uuid"
	worker "github.com/qninhdt/openlet/apps/workspace/internal/temporal"
	"github.com/qninhdt/openlet/apps/workspace/internal/user"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/qninhdt/openlet/packages/go/authz"
)

func (s *Server) members(c *gin.Context) {
	w, r := c.Writer, c.Request
	ws, e := resourceID(c, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	if _, e = s.Store.Authorize(r.Context(), ws, actorID(r), authz.MemberRead); e != nil {
		failure(w, r, e)
		return
	}
	scope := "members/" + ws.String()
	after, limit, e := page(r, scope)
	if e != nil {
		failure(w, r, e)
		return
	}
	items, e := s.Store.Members(r.Context(), ws, after, limit+1)
	if e != nil {
		failure(w, r, e)
		return
	}
	var next *string
	if len(items) > limit {
		items = items[:limit]
		next = cursor(scope, items[len(items)-1].UserID)
	}
	ids := make([]uuid.UUID, len(items))
	for i, v := range items {
		ids[i] = v.UserID
	}
	profiles, e := s.User.Summaries(r.Context(), ids)
	if e != nil {
		failure(w, r, e)
		return
	}
	type member struct {
		User user.Summary `json:"user"`
		Role string       `json:"role"`
	}
	out := make([]member, 0, len(items))
	for _, v := range items {
		out = append(out, member{User: profiles[v.UserID], Role: v.Role})
	}
	respond(w, 200, map[string]any{"items": out, "next_cursor": next})
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
	if _, e = worker.Mutate(r.Context(), s.Temporal, worker.Mutation{Kind: "member", WorkspaceID: ws, ActorID: actorID(r), TargetID: target, Role: in.Role, Remove: remove, Revision: revision}); e != nil {
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
	v, token, e := s.Store.Invite(r.Context(), ws, actorID(r), in.Email, in.Role)
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
	if _, e = s.Store.Authorize(r.Context(), ws, actorID(r), authz.InvitationRead); e != nil {
		failure(w, r, e)
		return
	}
	scope := "invitations/" + ws.String()
	after, limit, e := page(r, scope)
	if e != nil {
		failure(w, r, e)
		return
	}
	items, e := s.Store.Invitations(r.Context(), ws, after, limit+1)
	if e != nil {
		failure(w, r, e)
		return
	}
	var next *string
	if len(items) > limit {
		items = items[:limit]
		next = cursor(scope, items[len(items)-1].ID)
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
	if e = s.Store.RevokeInvite(r.Context(), ws, actorID(r), id); e != nil {
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
	if len(in.Token) != 43 {
		failure(w, r, workspace.Fault{Code: "INVITATION_INVALID"})
		return
	}
	hash := sha256.Sum256([]byte(in.Token))
	ws, e := s.Store.InvitationWorkspace(r.Context(), hash)
	if e != nil {
		failure(w, r, e)
		return
	}
	if _, e = worker.Mutate(r.Context(), s.Temporal, worker.Mutation{Kind: "invite", WorkspaceID: ws, ActorID: actorID(r), InvitationHash: hash}); e != nil {
		failure(w, r, e)
		return
	}
	resource, e := s.Store.Authorize(r.Context(), ws, actorID(r), authz.MemberRead)
	if e != nil {
		failure(w, r, e)
		return
	}
	profiles, e := s.User.Summaries(r.Context(), []uuid.UUID{actorID(r)})
	if e != nil {
		failure(w, r, e)
		return
	}
	w.Header().Set("Location", "/v1/workspaces/"+ws.String()+"/members/"+actorID(r).String())
	respond(w, 201, map[string]any{"workspace_id": ws, "user": profiles[actorID(r)], "role": resource.Role})
}
