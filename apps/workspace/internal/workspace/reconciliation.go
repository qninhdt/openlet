package workspace

import (
	"context"
	"encoding/json"
	"github.com/google/uuid"
)

type Pending struct {
	ID        uuid.UUID
	Status    string
	Provision Provision
}

func (s *Store) Pending(ctx context.Context) ([]Pending, error) {
	rows, err := s.DB.Query(ctx, `WITH pending AS (SELECT id FROM workspaces WHERE (status='provisioning' AND error_code IS NULL) OR status='deleting' ORDER BY updated_at,id LIMIT 100 FOR UPDATE SKIP LOCKED), rotated AS (UPDATE workspaces w SET updated_at=now() FROM pending p WHERE w.id=p.id RETURNING w.id,w.status,w.creation_workflow_id) SELECT r.id,r.status,r.creation_workflow_id,k.request_input FROM rotated r LEFT JOIN idempotency_keys k ON k.workspace_id=r.id AND k.completed_at IS NULL`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	values := []Pending{}
	for rows.Next() {
		var value Pending
		var input []byte
		if err = rows.Scan(&value.ID, &value.Status, &value.Provision.WorkflowID, &input); err != nil {
			return nil, err
		}
		if value.Status == "provisioning" {
			if err = json.Unmarshal(input, &value.Provision.Input); err != nil {
				return nil, err
			}
		}
		values = append(values, value)
	}
	return values, rows.Err()
}
func (s *Store) FailDeletion(ctx context.Context, id uuid.UUID) error {
	_, err := s.DB.Exec(ctx, `UPDATE workspaces SET error_code='WORKFLOW_FAILED',updated_at=now() WHERE id=$1 AND status='deleting'`, id)
	return err
}
func (s *Store) PruneReceipts(ctx context.Context) error {
	_, err := s.DB.Exec(ctx, `DELETE FROM idempotency_keys WHERE (actor_id,operation,request_key) IN (SELECT actor_id,operation,request_key FROM idempotency_keys WHERE expires_at<=now() ORDER BY expires_at LIMIT 100)`)
	return err
}

func (s *Store) UnreleasedProvisioning(ctx context.Context) ([]Storage, error) {
	rows, err := s.DB.Query(ctx, `WITH pending AS (SELECT w.id FROM workspaces w JOIN idempotency_keys k ON k.workspace_id=w.id WHERE w.status='active' AND k.completed_at IS NULL ORDER BY w.updated_at,w.id LIMIT 100 FOR UPDATE OF w SKIP LOCKED),rotated AS (UPDATE workspaces w SET updated_at=now() FROM pending p WHERE w.id=p.id RETURNING w.id,w.quota_bucket_id,w.filesystem_id,w.root_id,w.limit_bytes) SELECT id,quota_bucket_id,filesystem_id,root_id,limit_bytes::text FROM rotated`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	values := []Storage{}
	for rows.Next() {
		var value Storage
		if err = rows.Scan(&value.WorkspaceID, &value.BucketID, &value.FilesystemID, &value.RootID, &value.LimitBytes); err != nil {
			return nil, err
		}
		values = append(values, value)
	}
	return values, rows.Err()
}
