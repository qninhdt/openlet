//go:build integration

package filesystem

import (
	"context"
	"github.com/google/uuid"
)

func createTestScope(ctx context.Context, store *Store, key, filesystemID, scopeID uuid.UUID) (Scope, error) {
	values, err := store.CreateScopes(ctx, key, filesystemID, []uuid.UUID{scopeID}, true, true)
	if err != nil {
		return Scope{}, err
	}
	return values[0], nil
}
