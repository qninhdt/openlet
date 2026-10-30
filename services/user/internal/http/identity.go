package http

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	worker "openlet/services/user/internal/temporal"
	"openlet/services/user/internal/user"
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
func writeOnboarding(w http.ResponseWriter, status int, v user.Onboarding) {
	respond(w, status, map[string]any{"operation_id": v.OperationID, "user_id": v.UserID, "workspace_id": v.WorkspaceID, "state": v.State, "refresh_session": v.RefreshSession, "status_url": "/v1/onboarding"})
}
func (s *Server) refreshOnboarding(r *http.Request, v user.Onboarding) user.Onboarding {
	if v.State != "running" {
		return v
	}
	ctx, cancel := context.WithTimeout(r.Context(), time.Second)
	defer cancel()
	description, e := s.Temporal.DescribeWorkflowExecution(ctx, "onboard/"+r.Header.Get("X-Clerk-Sub"), "")
	if e == nil {
		switch description.WorkflowExecutionInfo.Status {
		case enums.WORKFLOW_EXECUTION_STATUS_FAILED, enums.WORKFLOW_EXECUTION_STATUS_CANCELED, enums.WORKFLOW_EXECUTION_STATUS_TERMINATED, enums.WORKFLOW_EXECUTION_STATUS_TIMED_OUT:
			if s.Store.Fail(ctx, r.Header.Get("X-Clerk-Sub")) == nil {
				v.State = "failed"
			}
		}
	}
	return v
}
func (s *Server) onboardingGet(w http.ResponseWriter, r *http.Request) {
	v, e := s.Store.Onboarding(r.Context(), r.Header.Get("X-Clerk-Sub"))
	if e != nil {
		failure(w, r, e)
		return
	}
	writeOnboarding(w, 200, s.refreshOnboarding(r, v))
}
func (s *Server) onboardingPost(w http.ResponseWriter, r *http.Request) {
	if key, e := uuid.Parse(r.Header.Get("Idempotency-Key")); e != nil || key == uuid.Nil {
		Error(w, r, 400, "VALIDATION", "UUID Idempotency-Key required")
		return
	}
	subject := r.Header.Get("X-Clerk-Sub")
	if v, e := s.Store.Onboarding(r.Context(), subject); e == nil {
		status := http.StatusOK
		if v.State == "running" {
			status = http.StatusAccepted
		}
		writeOnboarding(w, status, v)
		return
	} else {
		var f user.Fault
		if !errors.As(e, &f) || f.Code != "NOT_FOUND" {
			failure(w, r, e)
			return
		}
	}
	_, e := s.Temporal.ExecuteWorkflow(r.Context(), client.StartWorkflowOptions{ID: "onboard/" + subject, TaskQueue: worker.Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, worker.OnboardUser, subject)
	if e != nil {
		failure(w, r, e)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	for {
		v, e := s.Store.Onboarding(ctx, subject)
		if e == nil {
			status := http.StatusOK
			if v.State == "running" {
				status = http.StatusAccepted
			}
			writeOnboarding(w, status, v)
			return
		}
		select {
		case <-ctx.Done():
			w.Header().Set("Retry-After", "1")
			Error(w, r, 503, "ADMISSION_PENDING", "retry with the same key")
			return
		case <-ticker.C:
		}
	}
}
func (s *Server) me(w http.ResponseWriter, r *http.Request) {
	v, e := s.Store.Profile(r.Context(), identityID(r))
	if e != nil {
		failure(w, r, e)
		return
	}
	respond(w, 200, v)
}
func (s *Server) updateMe(w http.ResponseWriter, r *http.Request) {
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
func (s *Server) internal(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if len(r.Header.Values("Authorization")) != 1 || subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+s.Config.WorkspaceToken)) != 1 {
			Error(w, r, 401, "UNAUTHENTICATED", "service authentication required")
			return
		}
		next.ServeHTTP(w, r)
	})
}
func (s *Server) summaries(w http.ResponseWriter, r *http.Request) {
	var in struct {
		IDs []uuid.UUID `json:"ids"`
	}
	if e := decode(w, r, &in); e != nil {
		failure(w, r, e)
		return
	}
	seen := map[uuid.UUID]bool{}
	for _, id := range in.IDs {
		if id == uuid.Nil || seen[id] {
			failure(w, r, user.Fault{Code: "VALIDATION"})
			return
		}
		seen[id] = true
	}
	v, e := s.Store.Summaries(r.Context(), in.IDs)
	if e != nil {
		failure(w, r, e)
		return
	}
	respond(w, 200, map[string]any{"items": v})
}
func (s *Server) verifiedEmails(w http.ResponseWriter, r *http.Request) {
	id, e := uuid.Parse(chi.URLParam(r, "id"))
	if e != nil || id == uuid.Nil {
		failure(w, r, user.Fault{Code: "VALIDATION"})
		return
	}
	subject, e := s.Store.Subject(r.Context(), id)
	if e != nil {
		failure(w, r, e)
		return
	}
	emails, e := s.Clerk.VerifiedEmails(r.Context(), subject)
	if e != nil {
		failure(w, r, e)
		return
	}
	respond(w, 200, map[string]any{"emails": emails})
}
