package temporal

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"

	"github.com/google/uuid"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"openlet/services/user/internal/clerk"
	"openlet/services/user/internal/user"
)

const Queue = "openlet-user"

type Activities struct {
	Store               *user.Store
	Clerk               clerk.Client
	WorkspaceURL, Token string
}

func (a *Activities) EnsureUser(ctx context.Context, subject string) (user.Onboarding, error) {
	v, e := a.Store.EnsureUser(ctx, subject)
	var f user.Fault
	if errors.As(e, &f) {
		e = temporal.NewNonRetryableApplicationError(f.Code, f.Code, e)
	}
	return v, e
}
func (a *Activities) workspaceRequest(ctx context.Context, method, path string, body any, key uuid.UUID) (string, error) {
	var input io.Reader
	if body != nil {
		b, e := json.Marshal(body)
		if e != nil {
			return "", e
		}
		input = bytes.NewReader(b)
	}
	r, e := http.NewRequestWithContext(ctx, method, a.WorkspaceURL+path, input)
	if e != nil {
		return "", e
	}
	r.Header.Set("Authorization", "Bearer "+a.Token)
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Idempotency-Key", key.String())
	res, e := (&http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}).Do(r)
	if e != nil {
		return "", errors.New("Workspace unavailable")
	}
	defer res.Body.Close()
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		if res.StatusCode >= 400 && res.StatusCode < 500 {
			return "", temporal.NewNonRetryableApplicationError("workspace provisioning rejected", "WORKSPACE_REJECTED", nil)
		}
		return "", errors.New("Workspace unavailable")
	}
	var out struct {
		State       string    `json:"state"`
		WorkspaceID uuid.UUID `json:"workspace_id"`
	}
	if e = json.NewDecoder(io.LimitReader(res.Body, 65536)).Decode(&out); e != nil {
		return "", errors.New("invalid Workspace response")
	}
	return out.State, nil
}
func (a *Activities) EnsureInitialWorkspace(ctx context.Context, v user.Onboarding) (string, error) {
	return a.workspaceRequest(ctx, "POST", "/internal/v1/workspaces", map[string]any{"actor_id": v.UserID, "workspace_id": v.WorkspaceID, "name": "My workspace"}, v.WorkspaceKey)
}
func (a *Activities) GetInitialWorkspaceStatus(ctx context.Context, v user.Onboarding) (string, error) {
	return a.workspaceRequest(ctx, "GET", "/internal/v1/workspace-provisions/"+v.UserID.String()+"/"+v.WorkspaceKey.String(), nil, v.WorkspaceKey)
}
func (a *Activities) PublishClerkUserID(ctx context.Context, subject string, v user.Onboarding) error {
	return a.Clerk.PublishUserID(ctx, subject, v.UserID.String())
}
func (a *Activities) CompleteOnboarding(ctx context.Context, subject string) error {
	e := a.Store.Complete(ctx, subject)
	var f user.Fault
	if errors.As(e, &f) {
		return temporal.NewNonRetryableApplicationError(f.Code, f.Code, e)
	}
	return e
}
func (a *Activities) FailOnboarding(ctx context.Context, subject string) error {
	return a.Store.Fail(ctx, subject)
}
func OnboardUser(ctx workflow.Context, subject string) (result uuid.UUID, err error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var a *Activities
	var v user.Onboarding
	if e := workflow.ExecuteActivity(ctx, a.EnsureUser, subject).Get(ctx, &v); e != nil {
		return uuid.Nil, e
	}
	if v.State == "succeeded" {
		return v.OperationID, nil
	}
	defer func() {
		var continuing *workflow.ContinueAsNewError
		if err != nil && !errors.As(err, &continuing) {
			disconnected, cancel := workflow.NewDisconnectedContext(ctx)
			defer cancel()
			_ = workflow.ExecuteActivity(disconnected, a.FailOnboarding, subject).Get(disconnected, nil)
		}
	}()
	var state string
	if e := workflow.ExecuteActivity(ctx, a.EnsureInitialWorkspace, v).Get(ctx, &state); e != nil {
		return uuid.Nil, e
	}
	for polls := 0; state != "succeeded"; polls++ {
		if polls >= 200 {
			return uuid.Nil, workflow.NewContinueAsNewError(ctx, OnboardUser, subject)
		}
		if state == "failed" {
			return uuid.Nil, temporal.NewNonRetryableApplicationError("initial workspace failed", "WORKSPACE_FAILED", nil)
		}
		if e := workflow.Sleep(ctx, time.Second); e != nil {
			return uuid.Nil, e
		}
		if e := workflow.ExecuteActivity(ctx, a.GetInitialWorkspaceStatus, v).Get(ctx, &state); e != nil {
			return uuid.Nil, e
		}
	}
	if e := workflow.ExecuteActivity(ctx, a.PublishClerkUserID, subject, v).Get(ctx, nil); e != nil {
		return uuid.Nil, e
	}
	if e := workflow.ExecuteActivity(ctx, a.CompleteOnboarding, subject).Get(ctx, nil); e != nil {
		return uuid.Nil, e
	}
	return v.OperationID, nil
}
