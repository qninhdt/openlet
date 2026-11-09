package workspace

import (
	"context"
	"encoding/json"
	"io"

	"github.com/google/uuid"
)

// ExportResourceWorkspaces supplies owner-verified lifecycle facts to offline Leta recovery.
func (s *Store) ExportResourceWorkspaces(ctx context.Context, output io.Writer) error {
	encoder := json.NewEncoder(output)
	after := uuid.Nil
	for {
		ids, err := s.RelationshipIDs(ctx, after)
		if err != nil {
			return err
		}
		for _, id := range ids {
			value, err := s.resourceRecord(ctx, id)
			if err != nil {
				return err
			}
			if err = encoder.Encode(struct {
				WorkspaceID uuid.UUID `json:"workspace_id"`
				Status      string    `json:"status"`
			}{id, value.Status}); err != nil {
				return err
			}
			after = id
		}
		if len(ids) < 100 {
			return nil
		}
	}
}
