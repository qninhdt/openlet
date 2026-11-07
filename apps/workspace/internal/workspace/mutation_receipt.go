package workspace

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// MutationReceipt uses the existing receipt table to recover an acknowledged or lost SQL commit.
type MutationReceipt struct {
	Key  uuid.UUID
	Hash string
}

func mutationApplied(ctx context.Context, tx pgx.Tx, actor, ws uuid.UUID, receipt MutationReceipt) (bool, error) {
	var savedHash string
	var savedWorkspace uuid.UUID
	err := tx.QueryRow(ctx, `SELECT request_hash,workspace_id FROM idempotency_keys WHERE actor_id=$1 AND request_key=$2`, actor, receipt.Key).Scan(&savedHash, &savedWorkspace)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if savedHash != receipt.Hash || savedWorkspace != ws {
		return false, Fault{"IDEMPOTENCY_CONFLICT"}
	}
	return true, nil
}

func saveMutationReceipt(ctx context.Context, tx pgx.Tx, receipt MutationReceipt, actor, ws uuid.UUID) error {
	if receipt.Key == uuid.Nil {
		return nil
	}
	if receipt.Hash == "" {
		return Fault{"VALIDATION"}
	}
	_, err := tx.Exec(ctx, `INSERT INTO idempotency_keys(actor_id,request_key,request_hash,workspace_id) VALUES($1,$2,$3,$4)`, actor, receipt.Key, receipt.Hash, ws)
	return err
}

func (s *Store) CompleteMutation(ctx context.Context, actor uuid.UUID, receipt MutationReceipt) error {
	_, err := s.DB.Exec(ctx, `UPDATE idempotency_keys SET expires_at=COALESCE(expires_at,now()+interval '24 hours') WHERE actor_id=$1 AND request_key=$2 AND request_hash=$3`, actor, receipt.Key, receipt.Hash)
	return err
}
