package http

import (
	"net/http"

	"github.com/google/uuid"
	"openlet/services/workspace/internal/user"
	"openlet/services/workspace/internal/workspace"
)

func (s *Server) members(w http.ResponseWriter, r *http.Request) {
	ws, e := resourceID(r, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	if _, e = s.Store.Authorize(r.Context(), ws, actorID(r), "viewer"); e != nil {
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
func (s *Server) changeMember(w http.ResponseWriter, r *http.Request) {
	ws, e := resourceID(r, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	target, e := resourceID(r, "user")
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
	if e = s.Store.ChangeMember(r.Context(), ws, actorID(r), target, in.Role, remove); e != nil {
		failure(w, r, e)
		return
	}
	w.WriteHeader(204)
}
func (s *Server) transferOwnership(w http.ResponseWriter, r *http.Request) {
	ws, e := resourceID(r, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	var in struct {
		UserID uuid.UUID `json:"user_id"`
	}
	if e = decode(w, r, &in); e != nil {
		failure(w, r, e)
		return
	}
	if in.UserID == uuid.Nil {
		failure(w, r, workspace.Fault{Code: "VALIDATION"})
		return
	}
	if e = s.Store.Transfer(r.Context(), ws, actorID(r), in.UserID); e != nil {
		failure(w, r, e)
		return
	}
	w.WriteHeader(204)
}
func (s *Server) invite(w http.ResponseWriter, r *http.Request) {
	ws, e := resourceID(r, "ws")
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
	respond(w, 201, map[string]any{"invitation": v, "token": token})
}
func (s *Server) invitations(w http.ResponseWriter, r *http.Request) {
	ws, e := resourceID(r, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	if _, e = s.Store.Authorize(r.Context(), ws, actorID(r), "owner"); e != nil {
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
func (s *Server) revokeInvitation(w http.ResponseWriter, r *http.Request) {
	ws, e := resourceID(r, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	id, e := resourceID(r, "invitation")
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
func (s *Server) acceptInvitation(w http.ResponseWriter, r *http.Request) {
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
	emails, e := s.User.VerifiedEmails(r.Context(), actorID(r))
	if e != nil {
		failure(w, r, e)
		return
	}
	ws, e := s.Store.AcceptInvite(r.Context(), actorID(r), in.Token, emails)
	if e != nil {
		failure(w, r, e)
		return
	}
	respond(w, 200, map[string]any{"workspace_id": ws})
}
