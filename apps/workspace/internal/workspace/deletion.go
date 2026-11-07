package workspace

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type DeleteInput struct {
	WorkspaceID uuid.UUID
	ActorID     uuid.UUID
}

func (s *Service) MarkWorkspaceDeleting(ctx context.Context, in DeleteInput) (Workspace, error) {
	tx, err := s.Store.DB.Begin(ctx)
	if err != nil {
		return Workspace{}, err
	}
	defer tx.Rollback(ctx)
	value, err := s.Store.getInTransaction(ctx, tx, in.WorkspaceID, in.ActorID)
	if err != nil {
		return value, err
	}
	if _, err = tx.Exec(ctx, `UPDATE workspaces SET status='deleting',updated_at=now() WHERE id=$1 AND status='active'`, in.WorkspaceID); err != nil {
		return value, err
	}
	if value.Status == "active" {
		value.Status = "deleting"
	}
	return value, tx.Commit(ctx)
}
func (s *Service) RemoveWorkspace(ctx context.Context, id uuid.UUID) error {
	tx, err := s.Store.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	var state string
	err = tx.QueryRow(ctx, `SELECT status FROM workspaces WHERE id=$1 FOR UPDATE`, id).Scan(&state)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil
	}
	if err != nil {
		return err
	}
	if state != "deleting" && state != "deleted" {
		return Fault{"STATE_CONFLICT"}
	}
	if _, err = tx.Exec(ctx, `DELETE FROM workspace_invitations WHERE workspace_id=$1`, id); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `UPDATE workspaces SET status='deleted',updated_at=now() WHERE id=$1`, id); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}
	return s.Store.RemoveRelationships(ctx, s.Store.Graph, id)
}
