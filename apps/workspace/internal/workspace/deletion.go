package workspace

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"openlet/packages/go/authz"
)

type DeleteInput struct {
	ActorID     uuid.UUID `json:"actor_id"`
	WorkspaceID uuid.UUID `json:"workspace_id"`
	Revision    string    `json:"revision"`
}
type Deletion struct {
	Workspace Workspace `json:"workspace"`
	ActorID   uuid.UUID `json:"actor_id"`
}

func (s *Store) BeginDeletion(ctx context.Context, in DeleteInput) (Workspace, error) {
	if in.ActorID == uuid.Nil || in.WorkspaceID == uuid.Nil || in.Revision == "" {
		return Workspace{}, Fault{"VALIDATION"}
	}
	observed, err := s.Authorize(ctx, in.WorkspaceID, in.ActorID, authz.WorkspaceDelete)
	if err != nil {
		return observed, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return Workspace{}, err
	}
	defer tx.Rollback(ctx)
	value, err := s.lockAdmission(ctx, tx, observed, in.ActorID)
	if err != nil {
		return value, err
	}
	status := value.Status
	// A repeated DELETE of this tombstone cannot re-admit or recreate the resource.
	if status == "deleting" || status == "deleted" {
		return value, nil
	}
	if value.Revision != in.Revision {
		return value, Fault{"REVISION_MISMATCH"}
	}
	if status != "active" && status != "failed" {
		return value, Fault{"STATE_CONFLICT"}
	}
	err = tx.QueryRow(ctx, `UPDATE workspaces SET status='deleting',revision=revision+1,updated_at=now() WHERE id=$1 RETURNING revision::text`, in.WorkspaceID).Scan(&value.Revision)
	if err != nil {
		return value, err
	}
	value.Status = "deleting"
	return value, tx.Commit(ctx)
}
func (s *Store) Deletion(ctx context.Context, id uuid.UUID) (Deletion, error) {
	var actor uuid.UUID
	err := s.DB.QueryRow(ctx, `SELECT m.user_id FROM workspace_members m JOIN workspaces w ON w.id=m.workspace_id WHERE w.id=$1 AND m.role='owner' AND w.status IN ('deleting','deleted')`, id).Scan(&actor)
	if errors.Is(err, pgx.ErrNoRows) {
		return Deletion{}, Fault{"NOT_FOUND"}
	}
	if err != nil {
		return Deletion{}, err
	}
	value, err := s.Get(ctx, id, actor)
	return Deletion{Workspace: value, ActorID: actor}, err
}
func (s *Store) CompleteDeletion(ctx context.Context, id uuid.UUID) error {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	var status string
	if err = tx.QueryRow(ctx, `SELECT status FROM workspaces WHERE id=$1 FOR UPDATE`, id).Scan(&status); err != nil {
		return err
	}
	if status == "deleted" {
		return nil
	}
	if status != "deleting" {
		return Fault{"STATE_CONFLICT"}
	}
	if _, err = tx.Exec(ctx, `DELETE FROM workspace_invitations WHERE workspace_id=$1`, id); err != nil {
		return err
	}
	// Keep the owner on the tombstone so the caller can read the deletion result.
	if _, err = tx.Exec(ctx, `DELETE FROM workspace_members WHERE workspace_id=$1 AND role!='owner'`, id); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `UPDATE workspaces SET status='deleted',error_code=NULL,updated_at=now() WHERE id=$1`, id); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `UPDATE idempotency_keys SET completed_at=COALESCE(completed_at,now()),expires_at=COALESCE(expires_at,now()+interval '24 hours') WHERE workspace_id=$1`, id); err != nil {
		return err
	}
	return tx.Commit(ctx)
}
