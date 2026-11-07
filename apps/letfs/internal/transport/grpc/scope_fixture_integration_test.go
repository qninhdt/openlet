//go:build integration

package grpc

import (
	"context"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
)

func createTestScope(ctx context.Context, store *filesystem.Store, key, fs, scope uuid.UUID) (filesystem.Scope, error) {
	values, err := store.CreateScopes(ctx, key, fs, []uuid.UUID{scope}, true, true)
	if err != nil {
		return filesystem.Scope{}, err
	}
	return values[0], nil
}
