package workspace

import "context"

func (s *Store) PruneReceipts(ctx context.Context) error {
	_, err := s.DB.Exec(ctx, `DELETE FROM idempotency_keys WHERE (actor_id,request_key) IN (SELECT actor_id,request_key FROM idempotency_keys WHERE expires_at<=now() ORDER BY expires_at LIMIT 100)`)
	return err
}
