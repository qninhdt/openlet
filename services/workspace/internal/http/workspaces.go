package http

import (
	"context"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	worker "openlet/services/workspace/internal/temporal"
	"openlet/services/workspace/internal/workspace"
)

func decode(w http.ResponseWriter, r *http.Request, out any) error {
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16384))
	d.DisallowUnknownFields()
	if e := d.Decode(out); e != nil {
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
func resourceID(r *http.Request, name string) (uuid.UUID, error) {
	v, e := uuid.Parse(chi.URLParam(r, name))
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
func (s *Server) internal(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if len(r.Header.Values("Authorization")) != 1 || subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+s.Config.UserToken)) != 1 {
			Error(w, r, 401, "UNAUTHENTICATED", "service authentication required")
			return
		}
		next.ServeHTTP(w, r)
	})
}
func (s *Server) startCreate(w http.ResponseWriter, r *http.Request, in workspace.CreateInput) {
	key, e := uuid.Parse(r.Header.Get("Idempotency-Key"))
	if e != nil || key == uuid.Nil || in.ActorID == uuid.Nil {
		failure(w, r, workspace.Fault{Code: "VALIDATION"})
		return
	}
	in.Key = key
	if e = workspace.ValidateName(in.Name); e != nil {
		failure(w, r, e)
		return
	}
	fingerprint := workspace.Fingerprint(in)
	if op, err := s.Store.OperationByKey(r.Context(), in.ActorID, "create", key); err == nil {
		if op.Fingerprint != fingerprint {
			failure(w, r, workspace.Fault{Code: "IDEMPOTENCY_CONFLICT"})
			return
		}
		writeOperation(w, op)
		return
	} else {
		var f workspace.Fault
		if !errors.As(err, &f) || f.Code != "NOT_FOUND" {
			failure(w, r, err)
			return
		}
	}
	id := "create-workspace/" + in.ActorID.String() + "/" + key.String()
	// A closed run may have failed before DB admission; retain its original request identity.
	history := s.Temporal.GetWorkflowHistory(r.Context(), id, "", false, enums.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
	if history.HasNext() {
		event, err := history.Next()
		if err != nil {
			var missing *serviceerror.NotFound
			if !errors.As(err, &missing) {
				failure(w, r, err)
				return
			}
		} else if started := event.GetWorkflowExecutionStartedEventAttributes(); started != nil {
			var original workspace.CreateInput
			if err = converter.GetDefaultDataConverter().FromPayloads(started.Input, &original); err != nil {
				failure(w, r, err)
				return
			}
			if workspace.Fingerprint(original) != fingerprint {
				failure(w, r, workspace.Fault{Code: "IDEMPOTENCY_CONFLICT"})
				return
			}
		}
	}
	run, e := s.Temporal.ExecuteWorkflow(r.Context(), client.StartWorkflowOptions{ID: id, TaskQueue: worker.Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, worker.CreateWorkspace, in)
	if e != nil {
		failure(w, r, e)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	for {
		op, err := s.Store.OperationByKey(ctx, in.ActorID, "create", key)
		if err == nil {
			if op.Fingerprint != fingerprint {
				failure(w, r, workspace.Fault{Code: "IDEMPOTENCY_CONFLICT"})
				return
			}
			writeOperation(w, op)
			return
		}
		select {
		case <-ctx.Done():
			check, stop := context.WithTimeout(r.Context(), time.Second)
			defer stop()
			description, describeError := s.Temporal.DescribeWorkflowExecution(check, id, run.GetRunID())
			if describeError == nil && description.WorkflowExecutionInfo.Status != enums.WORKFLOW_EXECUTION_STATUS_RUNNING {
				var app *temporal.ApplicationError
				if err := run.Get(check, nil); errors.As(err, &app) {
					switch app.Type() {
					case "VALIDATION", "RESOURCE_LIMIT", "IDEMPOTENCY_CONFLICT", "STATE_CONFLICT":
						failure(w, r, workspace.Fault{Code: app.Type()})
						return
					}
				}
			}
			w.Header().Set("Retry-After", "1")
			Error(w, r, 503, "ADMISSION_PENDING", "retry with the same key")
			return
		case <-ticker.C:
		}
	}
}
func writeOperation(w http.ResponseWriter, op workspace.Operation) {
	status := 202
	if op.State != "running" {
		status = 200
	}
	respond(w, status, map[string]any{"operation_id": op.ID, "workspace_id": op.WorkspaceID, "kind": op.Kind, "state": op.State, "result": op.Result, "status_url": "/v1/workspaces/" + op.WorkspaceID.String() + "/operations/" + op.ID.String()})
}
func (s *Server) createWorkspace(w http.ResponseWriter, r *http.Request) {
	var in struct {
		Name string `json:"name"`
	}
	if e := decode(w, r, &in); e != nil {
		failure(w, r, e)
		return
	}
	s.startCreate(w, r, workspace.CreateInput{ActorID: actorID(r), Name: in.Name})
}
func (s *Server) internalCreate(w http.ResponseWriter, r *http.Request) {
	var in struct {
		ActorID     uuid.UUID `json:"actor_id"`
		WorkspaceID uuid.UUID `json:"workspace_id"`
		Name        string    `json:"name"`
	}
	if e := decode(w, r, &in); e != nil {
		failure(w, r, e)
		return
	}
	if in.WorkspaceID == uuid.Nil {
		failure(w, r, workspace.Fault{Code: "VALIDATION"})
		return
	}
	s.startCreate(w, r, workspace.CreateInput{ActorID: in.ActorID, WorkspaceID: in.WorkspaceID, Name: in.Name})
}
func (s *Server) internalProvisionStatus(w http.ResponseWriter, r *http.Request) {
	actor, e := resourceID(r, "actor")
	if e != nil {
		failure(w, r, e)
		return
	}
	key, e := resourceID(r, "key")
	if e != nil {
		failure(w, r, e)
		return
	}
	op, e := s.Store.OperationByKey(r.Context(), actor, "create", key)
	if e != nil {
		failure(w, r, e)
		return
	}
	respond(w, 200, s.refreshOperation(r, op))
}
func (s *Server) listWorkspaces(w http.ResponseWriter, r *http.Request) {
	scope := "workspaces/" + actorID(r).String()
	after, limit, e := page(r, scope)
	if e != nil {
		failure(w, r, e)
		return
	}
	items, e := s.Store.List(r.Context(), actorID(r), after, limit+1)
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
func (s *Server) getWorkspace(w http.ResponseWriter, r *http.Request) {
	id, e := resourceID(r, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	v, e := s.Store.Authorize(r.Context(), id, actorID(r), "viewer")
	if e != nil {
		failure(w, r, e)
		return
	}
	w.Header().Set("ETag", "\""+v.Revision+"\"")
	respond(w, 200, v)
}
func (s *Server) renameWorkspace(w http.ResponseWriter, r *http.Request) {
	id, e := resourceID(r, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	revision, e := precondition(r)
	if e != nil {
		failure(w, r, e)
		return
	}
	var in struct {
		Name string `json:"name"`
	}
	if e = decode(w, r, &in); e != nil {
		failure(w, r, e)
		return
	}
	v, e := s.Store.Rename(r.Context(), id, actorID(r), in.Name, revision)
	if e != nil {
		failure(w, r, e)
		return
	}
	w.Header().Set("ETag", "\""+v.Revision+"\"")
	respond(w, 200, v)
}
func (s *Server) getOperation(w http.ResponseWriter, r *http.Request) {
	ws, e := resourceID(r, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	id, e := resourceID(r, "op")
	if e != nil {
		failure(w, r, e)
		return
	}
	v, e := s.Store.Operation(r.Context(), id)
	if e != nil {
		var f workspace.Fault
		if errors.As(e, &f) && f.Code == "NOT_FOUND" {
			s.fileOperation(w, r, ws, id)
			return
		}
		failure(w, r, e)
		return
	}
	if v.WorkspaceID != ws {
		failure(w, r, workspace.Fault{Code: "NOT_FOUND"})
		return
	}
	if v.ActorID != actorID(r) {
		if _, e = s.Store.Authorize(r.Context(), ws, actorID(r), "owner"); e != nil {
			failure(w, r, workspace.Fault{Code: "NOT_FOUND"})
			return
		}
	}
	v = s.refreshOperation(r, v)
	respond(w, 200, v)
}

func (s *Server) refreshOperation(r *http.Request, v workspace.Operation) workspace.Operation {
	if v.State == "running" && v.Kind == "create" {
		ctx, cancel := context.WithTimeout(r.Context(), time.Second)
		defer cancel()
		id := "create-workspace/" + v.ActorID.String() + "/" + v.Key.String()
		description, err := s.Temporal.DescribeWorkflowExecution(ctx, id, "")
		if err == nil {
			switch description.WorkflowExecutionInfo.Status {
			case enums.WORKFLOW_EXECUTION_STATUS_FAILED, enums.WORKFLOW_EXECUTION_STATUS_CANCELED, enums.WORKFLOW_EXECUTION_STATUS_TERMINATED, enums.WORKFLOW_EXECUTION_STATUS_TIMED_OUT:
				if s.Store.Fail(ctx, v.ID) == nil {
					v.State = "failed"
				}
			}
		}
	}
	return v
}
