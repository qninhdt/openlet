package workspace

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"openlet/packages/go/authz"
)

func (s *Store) Authorize(ctx context.Context, ws, actor uuid.UUID, action authz.Action) (Workspace, error) {
	value, err := s.Get(ctx, ws, actor)
	if err != nil {
		return value, err
	}
	if action != authz.WorkspaceRead && action != authz.WorkspaceDelete {
		if err = value.checkActive(); err != nil {
			return value, err
		}
	}
	resource := authz.Resource{Type: "workspace", ID: ws.String()}
	if s.Graph == nil {
		return value, errors.New("authorization unavailable")
	}
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	allowed, err := authz.Check(ctx, s.Graph, actor.String(), action, resource)
	if err != nil {
		return value, err
	}
	if !allowed {
		return value, Fault{"FORBIDDEN"}
	}
	return value, nil
}

// Recheck local identity/version after graph admission, without holding a SQL lock across RPC.
func (s *Store) lockAdmission(ctx context.Context, tx pgx.Tx, observed Workspace, actor uuid.UUID) (Workspace, error) {
	if _, err := tx.Exec(ctx, `SELECT id FROM workspaces WHERE id=$1 FOR UPDATE`, observed.ID); err != nil {
		return Workspace{}, err
	}
	value, err := s.getInTransaction(ctx, tx, observed.ID, actor)
	if err != nil {
		return value, err
	}
	if value.Revision != observed.Revision || value.Status != observed.Status {
		return value, Fault{"REVISION_MISMATCH"}
	}
	return value, nil
}
