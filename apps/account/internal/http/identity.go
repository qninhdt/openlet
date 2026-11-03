package http

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	worker "openlet/apps/account/internal/temporal"
	"openlet/apps/account/internal/user"
	"openlet/packages/go/authz"
)

func decode(w http.ResponseWriter, r *http.Request, out any) error {
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16384))
	d.DisallowUnknownFields()
	if e := d.Decode(out); e != nil {
		return user.Fault{Code: "VALIDATION"}
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return user.Fault{Code: "VALIDATION"}
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
	var f user.Fault
	if errors.As(e, &f) {
		status := 400
		if f.Code == "NOT_FOUND" {
			status = 404
		}
		Error(w, r, status, f.Code, strings.ToLower(strings.ReplaceAll(f.Code, "_", " ")))
		return
	}
	Error(w, r, 503, "DEPENDENCY_UNAVAILABLE", "dependency unavailable")
}
func identityID(r *http.Request) uuid.UUID { return uuid.MustParse(r.Header.Get("X-Openlet-User-ID")) }
func writeOnboarding(w http.ResponseWriter, status int, value user.Onboarding) {
	w.Header().Set("Location", "/v1/me/onboarding")
	respond(w, status, value)
}
func (s *Server) onboardingGet(c *gin.Context) {
	value, err := s.Store.Onboarding(c.Request.Context(), c.GetHeader("X-Clerk-Sub"))
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	writeOnboarding(c.Writer, http.StatusOK, value)
}
func (s *Server) onboardingPut(c *gin.Context) {
	value, err := s.Store.EnsureUser(c.Request.Context(), c.GetHeader("X-Clerk-Sub"))
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	status := http.StatusOK
	if value.Status == "provisioning" {
		status = http.StatusAccepted
		dispatch, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
		defer cancel()
		if err = worker.StartOnboarding(dispatch, s.Temporal, c.GetHeader("X-Clerk-Sub")); err != nil {
			slog.WarnContext(c.Request.Context(), "onboarding admitted; workflow dispatch deferred")
		}
	}
	writeOnboarding(c.Writer, status, value)
}
func (s *Server) me(c *gin.Context) {
	w, r := c.Writer, c.Request
	v, e := s.Store.Profile(r.Context(), identityID(r))
	if e != nil {
		failure(w, r, e)
		return
	}
	if !s.authorizeAccount(c, authz.AccountRead) {
		return
	}
	respond(w, 200, v)
}
func (s *Server) updateMe(c *gin.Context) {
	w, r := c.Writer, c.Request
	if _, err := s.Store.Profile(r.Context(), identityID(r)); err != nil {
		failure(w, r, err)
		return
	}
	if !s.authorizeAccount(c, authz.AccountUpdate) {
		return
	}
	var in struct {
		Name   *string `json:"display_name"`
		Avatar *string `json:"avatar_url"`
	}
	if e := decode(w, r, &in); e != nil {
		failure(w, r, e)
		return
	}
	if in.Name == nil && in.Avatar == nil {
		failure(w, r, user.Fault{Code: "VALIDATION"})
		return
	}
	v, e := s.Store.UpdateProfile(r.Context(), identityID(r), in.Name, in.Avatar)
	if e != nil {
		failure(w, r, e)
		return
	}
	respond(w, 200, v)
}

func (s *Server) authorizeAccount(c *gin.Context, action authz.Action) bool {
	if s.Graph == nil {
		Error(c.Writer, c.Request, 503, "DEPENDENCY_UNAVAILABLE", "authorization unavailable")
		return false
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 2*time.Second)
	defer cancel()
	id := identityID(c.Request).String()
	allowed, err := authz.Check(ctx, s.Graph, id, action, authz.Resource{Type: "account", ID: id})
	if err != nil {
		failure(c.Writer, c.Request, err)
		return false
	}
	if !allowed {
		Error(c.Writer, c.Request, 403, "FORBIDDEN", "permission denied")
	}
	return allowed
}
