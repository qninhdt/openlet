//go:build integration

package filesystem

import (
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
)

func TestIntegrationStableProvisioningIdentity(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	s := Store{DB: db, MaxNodes: 100}
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "workspace"})
	id, key, scope := uuid.Must(uuid.NewV7()), uuid.New(), uuid.Must(uuid.NewV7())
	input := CreateFilesystem{ID: id, LimitBytes: 100}
	var group sync.WaitGroup
	errs := make(chan error, 8)
	for range 8 {
		group.Go(func() { _, err := s.CreateFilesystem(ctx, key, input); errs <- err })
	}
	group.Wait()
	close(errs)
	for err := range errs {
		require.NoError(t, err)
	}
	var count int
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM filesystems").Scan(&count))
	require.Equal(t, 1, count)
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM nodes").Scan(&count))
	require.Zero(t, count, "generic filesystem provisioning creates no scopes")
	_, err := s.CreateFilesystem(ctx, key, CreateFilesystem{ID: id, LimitBytes: 101})
	require.Error(t, err)
	rollback := uuid.Must(uuid.NewV7())
	_, err = s.CreateFilesystem(ctx, key, CreateFilesystem{ID: rollback, LimitBytes: 100})
	require.Error(t, err)
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM filesystems WHERE id=$1", rollback).Scan(&count))
	require.Zero(t, count)
	scopes, err := s.CreateScopes(ctx, uuid.New(), id, []uuid.UUID{scope}, true, true)
	require.NoError(t, err)
	again, err := s.CreateScopes(ctx, uuid.New(), id, []uuid.UUID{scope}, true, true)
	require.NoError(t, err)
	require.Equal(t, scopes, again)
	require.NoError(t, db.QueryRow(ctx, "SELECT node_count FROM filesystems WHERE id=$1", id).Scan(&count))
	require.Equal(t, 1, count)
	_, err = s.ListScopesForDeletion(ctx, id, uuid.Nil)
	require.NoError(t, err)
	_, err = s.CreateScopes(ctx, uuid.New(), id, []uuid.UUID{uuid.Must(uuid.NewV7())}, true, true)
	require.Error(t, err, "deletion fence blocks new scopes")
	require.NoError(t, s.DeleteScopeData(ctx, id, scope))
	require.NoError(t, s.DeleteScopeData(ctx, id, scope))
	require.NoError(t, s.RemoveFilesystem(ctx, id))
	require.NoError(t, s.RemoveFilesystem(ctx, id))
	require.NoError(t, db.QueryRow(ctx, "SELECT node_count FROM filesystems WHERE id=$1", id).Scan(&count))
	require.Zero(t, count)
}
