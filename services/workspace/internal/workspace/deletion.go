package workspace

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

type DeleteInput struct {
	ActorID     uuid.UUID `json:"actor_id"`
	WorkspaceID uuid.UUID `json:"workspace_id"`
	Key         uuid.UUID `json:"request_key"`
	Revision    string    `json:"revision"`
}
type Deletion struct {
	ActorID   uuid.UUID
	Operation Operation
	Storage   Storage
	Cursor    uuid.UUID
}

func (s *Store) BeginDeletion(ctx context.Context, in DeleteInput) (Deletion, error) {
	var out Deletion
	if in.ActorID == uuid.Nil || in.WorkspaceID == uuid.Nil || in.Key == uuid.Nil || in.Revision == "" {
		return out, Fault{"VALIDATION"}
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return out, e
	}
	defer tx.Rollback(ctx)
	var state string
	e = tx.QueryRow(ctx, `SELECT state FROM workspaces WHERE id=$1 FOR UPDATE`, in.WorkspaceID).Scan(&state)
	if errors.Is(e, pgx.ErrNoRows) {
		return out, Fault{"NOT_FOUND"}
	}
	if e != nil {
		return out, e
	}
	op, e := scanOperation(tx.QueryRow(ctx, `SELECT `+opColumns+` FROM operations WHERE actor_id=$1 AND kind='delete' AND request_key=$2`, in.ActorID, in.Key))
	if e == nil {
		if op.Fingerprint != Fingerprint(in) {
			return out, Fault{"IDEMPOTENCY_CONFLICT"}
		}
	} else {
		var f Fault
		if !errors.As(e, &f) || f.Code != "NOT_FOUND" {
			return out, e
		}
		ws, e := authorize(ctx, tx, in.WorkspaceID, in.ActorID, "owner")
		if e != nil {
			return out, e
		}
		if ws.Revision != in.Revision {
			return out, Fault{"REVISION_MISMATCH"}
		}
		op = Operation{ID: uuid.Must(uuid.NewV7()), WorkspaceID: in.WorkspaceID, ActorID: in.ActorID, Kind: "delete", Key: in.Key, Fingerprint: Fingerprint(in), State: "running"}
		_, e = tx.Exec(ctx, `INSERT INTO operations(id,workspace_id,actor_id,kind,request_key,fingerprint) VALUES($1,$2,$3,'delete',$4,$5)`, op.ID, in.WorkspaceID, in.ActorID, in.Key, op.Fingerprint)
		if e != nil {
			return out, e
		}
		_, e = tx.Exec(ctx, `UPDATE workspaces SET state='deleting',revision=revision+1,updated_at=now() WHERE id=$1`, in.WorkspaceID)
		if e != nil {
			return out, e
		}
	}
	out.Operation = op
	out.ActorID = op.ActorID
	if e = tx.Commit(ctx); e != nil {
		return out, e
	}
	return s.Deletion(ctx, out.Operation.ID)
}
func (s *Store) Deletion(ctx context.Context, id uuid.UUID) (Deletion, error) {
	var out Deletion
	op, e := s.Operation(ctx, id)
	if e != nil {
		return out, e
	}
	if op.Kind != "delete" {
		return out, Fault{"NOT_FOUND"}
	}
	out.Operation = op
	out.ActorID = op.ActorID
	out.Storage, e = s.Storage(ctx, op.WorkspaceID)
	if e != nil {
		return out, e
	}
	e = s.DB.QueryRow(ctx, `SELECT deletion_cursor FROM operations WHERE id=$1`, id).Scan(&out.Cursor)
	return out, e
}
func (s *Store) AdvanceDeletion(ctx context.Context, op, filesystem uuid.UUID) error {
	_, e := s.DB.Exec(ctx, `UPDATE operations SET deletion_cursor=greatest(deletion_cursor,$2),updated_at=now() WHERE id=$1 AND kind='delete' AND state='running'`, op, filesystem)
	return e
}
func (s *Store) CompleteDeletion(ctx context.Context, id uuid.UUID) error {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	var ws uuid.UUID
	if e = tx.QueryRow(ctx, `SELECT workspace_id FROM operations WHERE id=$1 AND kind='delete'`, id).Scan(&ws); e != nil {
		return e
	}
	var state string
	if e = tx.QueryRow(ctx, `SELECT state FROM workspaces WHERE id=$1 FOR UPDATE`, ws).Scan(&state); e != nil {
		return e
	}
	if state == "deleted" {
		return nil
	}
	if state != "deleting" {
		return Fault{"STATE_CONFLICT"}
	}
	if _, e = tx.Exec(ctx, `DELETE FROM workspace_invitations WHERE workspace_id=$1`, ws); e != nil {
		return e
	}
	if _, e = tx.Exec(ctx, `DELETE FROM workspace_members WHERE workspace_id=$1`, ws); e != nil {
		return e
	}
	if _, e = tx.Exec(ctx, `UPDATE workspaces SET state='deleted',updated_at=now() WHERE id=$1`, ws); e != nil {
		return e
	}
	if _, e = tx.Exec(ctx, `UPDATE operations SET state='succeeded',result=jsonb_build_object('workspace_id',workspace_id,'state','deleted'),updated_at=now() WHERE id=$1`, id); e != nil {
		return e
	}
	return tx.Commit(ctx)
}
