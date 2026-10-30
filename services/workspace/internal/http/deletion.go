package http

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"net/http"
	worker "openlet/services/workspace/internal/temporal"
	"openlet/services/workspace/internal/workspace"
	"time"
)

func (s *Server) deleteWorkspace(w http.ResponseWriter, r *http.Request) {
	ws, e := resourceID(r, "ws")
	if e != nil {
		failure(w, r, e)
		return
	}
	revision, e := precondition(r)
	if e != nil {
		failure(w, r, e)
		return
	}
	key, e := uuid.Parse(r.Header.Get("Idempotency-Key"))
	if e != nil || key == uuid.Nil {
		failure(w, r, workspace.Fault{Code: "VALIDATION"})
		return
	}
	in := workspace.DeleteInput{ActorID: actorID(r), WorkspaceID: ws, Key: key, Revision: revision}
	fp := workspace.Fingerprint(in)
	argument := worker.DeleteWorkflowInput{Start: &in}
	op, err := s.Store.OperationByKey(r.Context(), in.ActorID, "delete", key)
	if err == nil {
		if op.Fingerprint != fp {
			failure(w, r, workspace.Fault{Code: "IDEMPOTENCY_CONFLICT"})
			return
		}
		if op.State != "running" {
			writeOperation(w, op)
			return
		}
		argument = worker.DeleteWorkflowInput{OperationID: op.ID}
	} else {
		var f workspace.Fault
		if !errors.As(err, &f) || f.Code != "NOT_FOUND" {
			failure(w, r, err)
			return
		}
		if _, e = s.Store.Authorize(r.Context(), ws, in.ActorID, "owner"); e != nil {
			failure(w, r, e)
			return
		}
	}
	id := "delete-workspace/" + in.ActorID.String() + "/" + key.String()
	if argument.Start != nil {
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
				var original worker.DeleteWorkflowInput
				if e = converter.GetDefaultDataConverter().FromPayloads(started.Input, &original); e != nil {
					failure(w, r, e)
					return
				}
				if original.Start == nil || workspace.Fingerprint(*original.Start) != fp {
					failure(w, r, workspace.Fault{Code: "IDEMPOTENCY_CONFLICT"})
					return
				}
			}
		}
	}
	run, e := s.Temporal.ExecuteWorkflow(r.Context(), client.StartWorkflowOptions{ID: id, TaskQueue: worker.Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, worker.DeleteWorkspace, argument)
	if e != nil {
		failure(w, r, e)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	ticker := time.NewTicker(50 * time.Millisecond)
	defer ticker.Stop()
	for {
		op, e = s.Store.OperationByKey(ctx, in.ActorID, "delete", key)
		if e == nil {
			if op.Fingerprint != fp {
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
			description, err := s.Temporal.DescribeWorkflowExecution(check, id, run.GetRunID())
			if err == nil && description.WorkflowExecutionInfo.Status != enums.WORKFLOW_EXECUTION_STATUS_RUNNING {
				var app *temporal.ApplicationError
				if e = run.Get(check, nil); errors.As(e, &app) {
					switch app.Type() {
					case "VALIDATION", "NOT_FOUND", "FORBIDDEN", "REVISION_MISMATCH", "IDEMPOTENCY_CONFLICT", "WORKSPACE_DELETING":
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
