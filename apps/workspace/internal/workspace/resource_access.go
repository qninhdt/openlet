package workspace

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
	letaclient "github.com/qninhdt/openlet/packages/go/clients/leta"
	"github.com/qninhdt/openlet/packages/go/identity"
)

func unavailable() error {
	return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "required dependency unavailable")
}

func (s *Service) letaBinding(ctx context.Context, ws, id uuid.UUID) (letaclient.Binding, error) {
	if s.Letas == nil {
		return letaclient.Binding{}, unavailable()
	}
	binding, err := s.Letas.GetBinding(ctx, id)
	if err != nil {
		return binding, err
	}
	if binding.LetaID != id || binding.WorkspaceID != ws {
		return binding, Fault{"NOT_FOUND"}
	}
	return binding, nil
}

// Runtime admission uses canonical resource binding, never a human membership alias.
func (s *Service) resourceWorkspace(ctx context.Context, ws uuid.UUID, actor identity.Actor) (Workspace, *letaclient.Binding, error) {
	if !actor.Valid() || ws == uuid.Nil {
		return Workspace{}, nil, Fault{"VALIDATION"}
	}
	if actor.Kind == identity.User {
		value, err := s.Store.Authorize(ctx, ws, actor.ID, authz.WorkspaceRead)
		if err == nil {
			err = value.checkActive()
		}
		return value, nil, err
	}
	binding, err := s.letaBinding(ctx, ws, actor.ID)
	if err != nil {
		return Workspace{}, nil, err
	}
	if binding.Status != "active" {
		return Workspace{}, nil, Fault{"STATE_CONFLICT"}
	}
	var value Workspace
	err = s.Store.DB.QueryRow(ctx, `SELECT id,name,filesystem_id,shared_scope_id,status FROM workspaces WHERE id=$1`, ws).
		Scan(&value.ID, &value.Name, &value.FilesystemID, &value.SharedScopeID, &value.Status)
	if errors.Is(err, pgx.ErrNoRows) {
		return value, nil, Fault{"NOT_FOUND"}
	}
	if err == nil {
		err = value.checkActive()
	}
	return value, &binding, err
}

func (s *Service) inspectLeta(ctx context.Context, id, user uuid.UUID) error {
	check, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	allowed, err := authz.Check(check, s.Store.Graph, identity.Actor{Kind: identity.User, ID: user}, authz.LetaRead, authz.Resource{Type: "leta", ID: id.String()})
	if err != nil {
		return err
	}
	if !allowed {
		return Fault{"FORBIDDEN"}
	}
	return nil
}
