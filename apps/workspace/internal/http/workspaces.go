package http

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	worker "openlet/apps/workspace/internal/temporal"
	"openlet/apps/workspace/internal/workspace"
	"openlet/packages/go/authz"
)

func decode(w http.ResponseWriter, r *http.Request, out any) error {
	return decodeLimited(w, r, out, 16384)
}
func decodeLimited(w http.ResponseWriter, r *http.Request, out any, limit int64) error {
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, limit))
	d.DisallowUnknownFields()
	if e := d.Decode(out); e != nil {
		var oversized *http.MaxBytesError
		if errors.As(e, &oversized) {
			return workspace.Fault{Code: "REQUEST_LIMIT"}
		}
		return workspace.Fault{Code: "VALIDATION"}
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return workspace.Fault{Code: "VALIDATION"}
	}
	return nil
}
func respond(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func failure(w http.ResponseWriter, r *http.Request, e error) {
	var f workspace.Fault
	if errors.As(e, &f) {
		status := 409
		switch f.Code {
		case "REQUEST_LIMIT":
			status = 413
		case "VALIDATION":
			status = 400
		case "FORBIDDEN", "INVITATION_EMAIL_MISMATCH":
			status = 403
		case "NOT_FOUND":
			status = 404
		case "REVISION_MISMATCH":
			status = 412
		case "PRECONDITION_REQUIRED":
			status = 428
		}
		Error(w, r, status, f.Code, strings.ToLower(strings.ReplaceAll(f.Code, "_", " ")))
		return
	}
	Error(w, r, 503, "DEPENDENCY_UNAVAILABLE", "dependency unavailable")
}
func actorID(r *http.Request) uuid.UUID { return uuid.MustParse(r.Header.Get("X-Openlet-User-ID")) }
func resourceID(c *gin.Context, name string) (uuid.UUID, error) {
	v, e := uuid.Parse(c.Param(name))
	if e != nil || v == uuid.Nil {
		return uuid.Nil, workspace.Fault{Code: "VALIDATION"}
	}
	return v, nil
}
func precondition(r *http.Request) (string, error) {
	v := r.Header.Get("If-Match")
	if v == "" {
		return "", workspace.Fault{Code: "PRECONDITION_REQUIRED"}
	}
	if len(r.Header.Values("If-Match")) != 1 || len(v) < 3 || v[0] != '"' || v[len(v)-1] != '"' {
		return "", workspace.Fault{Code: "VALIDATION"}
	}
	value := v[1 : len(v)-1]
	number, e := strconv.ParseInt(value, 10, 64)
	if e != nil || number <= 0 || strconv.FormatInt(number, 10) != value {
		return "", workspace.Fault{Code: "VALIDATION"}
	}
	return value, nil
}
func pageLimit(r *http.Request) (int, error) {
	limit := 50
	if v := r.URL.Query().Get("limit"); v != "" {
		n, e := strconv.Atoi(v)
		if e != nil || n < 1 || n > 100 {
			return 0, workspace.Fault{Code: "VALIDATION"}
		}
		limit = n
	}
	return limit, nil
}
func page(r *http.Request, scope string) (uuid.UUID, int, error) {
	limit, e := pageLimit(r)
	if e != nil {
		return uuid.Nil, 0, e
	}
	after := uuid.Nil
	if cursor := r.URL.Query().Get("cursor"); cursor != "" {
		if len(cursor) > 512 {
			return after, 0, workspace.Fault{Code: "VALIDATION"}
		}
		decoded, e := base64.RawURLEncoding.DecodeString(cursor)
		if e != nil {
			return after, 0, workspace.Fault{Code: "VALIDATION"}
		}
		parts := strings.Split(string(decoded), "|")
		if len(parts) != 2 || parts[0] != scope {
			return after, 0, workspace.Fault{Code: "VALIDATION"}
		}
		after, e = uuid.Parse(parts[1])
		if e != nil {
			return after, 0, workspace.Fault{Code: "VALIDATION"}
		}
	}
	return after, limit, nil
}
func cursor(scope string, id uuid.UUID) *string {
	v := base64.RawURLEncoding.EncodeToString([]byte(scope + "|" + id.String()))
	return &v
}
func (s *Server) startCreate(w http.ResponseWriter, r *http.Request, in workspace.CreateInput) {
	key, err := uuid.Parse(r.Header.Get("Idempotency-Key"))
	if len(r.Header.Values("Idempotency-Key")) != 1 || err != nil || key == uuid.Nil {
		failure(w, r, workspace.Fault{Code: "VALIDATION"})
		return
	}
	in.Key = key
	admission, err := s.Store.EnsureWorkspace(r.Context(), in)
	if err != nil {
		failure(w, r, err)
		return
	}
	if admission.Status == "provisioning" {
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		if err = worker.StartCreate(ctx, s.Temporal, admission.ID); err != nil {
			slog.WarnContext(r.Context(), "workspace dispatch deferred", "workspace_id", admission.ID, "reason", err.Error())
		}
	}
	w.Header().Set("Location", "/v1/workspaces/"+admission.ID.String())
	w.Header().Set("ETag", "\""+admission.Revision+"\"")
	status := 202
	if admission.Status != "provisioning" {
		status = 200
	}
	respond(w, status, admission)
}
func (s *Server) createWorkspace(c *gin.Context) {
	w, r := c.Writer, c.Request
	var in struct {
		Name string `json:"name"`
	}
	if e := decode(w, r, &in); e != nil {
		failure(w, r, e)
		return
	}
	s.startCreate(w, r, workspace.CreateInput{ActorID: actorID(r), Name: in.Name})
}
func (s *Server) listWorkspaces(c *gin.Context) {
	w, r := c.Writer, c.Request
	scope := "workspaces/" + actorID(r).String()
	after, limit, e := page(r, scope)
	if e != nil {
		failure(w, r, e)
		return
	}
	items, e := s.Store.List(r.Context(), actorID(r), after, limit)
	if e != nil {
		failure(w, r, e)
		return
	}
	var next *string
	if len(items) == limit {
		next = cursor(scope, items[len(items)-1].ID)
	}
	resources := make([]authz.Resource, len(items))
	for i, item := range items {
		resources[i] = authz.Resource{Type: "workspace", ID: item.ID.String()}
	}
	if len(items) > 0 {
		ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
		defer cancel()
		allowed, err := authz.BulkCheck(ctx, s.Store.Graph, actorID(r).String(), authz.WorkspaceRead, resources)
		if err != nil {
			failure(w, r, err)
			return
		}
		visible := items[:0]
		for i, item := range items {
			if allowed[i] {
				visible = append(visible, item)
			}
		}
		items = visible
	}
	respond(w, 200, map[string]any{"items": items, "next_cursor": next})
}
func (s *Server) getWorkspace(c *gin.Context) {
	w, r := c.Writer, c.Request
	id, e := resourceID(c, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	v, e := s.Store.Authorize(r.Context(), id, actorID(r), authz.WorkspaceRead)
	if e != nil {
		failure(w, r, e)
		return
	}
	w.Header().Set("ETag", "\""+v.Revision+"\"")
	respond(w, 200, v)
}
func (s *Server) updateWorkspace(c *gin.Context) {
	w, r := c.Writer, c.Request
	id, e := resourceID(c, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	revision, e := precondition(r)
	if e != nil {
		failure(w, r, e)
		return
	}
	var in workspace.UpdateInput
	if e = decode(w, r, &in); e != nil {
		failure(w, r, e)
		return
	}
	v, e := s.Store.Update(r.Context(), id, actorID(r), revision, in)
	if e != nil {
		failure(w, r, e)
		return
	}
	if in.OwnerID != nil {
		if e = worker.SyncRelationships(r.Context(), s.Temporal, s.Store, id); e != nil {
			Error(w, r, 503, "DEPENDENCY_UNAVAILABLE", "workspace change committed; authorization synchronization incomplete")
			return
		}
	}
	w.Header().Set("ETag", "\""+v.Revision+"\"")
	respond(w, 200, v)
}
