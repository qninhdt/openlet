//go:build integration

package filesystem

import (
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
)

func TestIntegrationListScopesIsReadOnlyAndFilesystemBound(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	store := Store{DB: db, MaxNodes: 100}
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "workspace"})
	fs, foreign := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	for _, id := range []uuid.UUID{fs, foreign} {
		_, err := store.CreateFilesystem(ctx, uuid.New(), CreateFilesystem{ID: id})
		require.NoError(t, err)
	}
	ids := []uuid.UUID{uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())}
	scopes, err := store.CreateScopes(ctx, uuid.New(), fs, ids, true, false)
	require.NoError(t, err)
	_, err = store.CreateScopes(ctx, uuid.New(), foreign, []uuid.UUID{uuid.Must(uuid.NewV7())}, true, true)
	require.NoError(t, err)
	limit := int32(1)
	first, err := store.ListScopes(ctx, fs, nil, &limit)
	require.NoError(t, err)
	require.Equal(t, scopes[:1], first.Items)
	require.NotNil(t, first.NextCursor)
	_, err = store.ListScopes(ctx, foreign, first.NextCursor, &limit)
	require.Equal(t, apperr.Invalid, apperr.KindOf(err))
	second, err := store.ListScopes(ctx, fs, first.NextCursor, &limit)
	require.NoError(t, err)
	require.Equal(t, scopes[1:2], second.Items)
	last, err := store.ListScopes(ctx, fs, second.NextCursor, &limit)
	require.NoError(t, err)
	require.Equal(t, scopes[2:], last.Items)
	require.Nil(t, last.NextCursor)
	var state string
	var nodes int
	require.NoError(t, db.QueryRow(ctx, "SELECT state,node_count FROM filesystems WHERE id=$1", fs).Scan(&state, &nodes))
	require.Equal(t, "active", state)
	require.Equal(t, 3, nodes)
	// Inactive storage is omitted without initiating any deletion.
	_, err = db.Exec(ctx, "UPDATE scopes SET state='deleting' WHERE id=$1", ids[1])
	require.NoError(t, err)
	listed, err := store.ListScopes(ctx, fs, nil, nil)
	require.NoError(t, err)
	require.Equal(t, []Scope{scopes[0], scopes[2]}, listed.Items)
	_, err = db.Exec(ctx, "UPDATE filesystems SET state='deleting' WHERE id=$1", fs)
	require.NoError(t, err)
	_, err = store.ListScopes(ctx, fs, nil, nil)
	require.Equal(t, apperr.Missing, apperr.KindOf(err))
	_, err = store.ListScopes(ctx, uuid.New(), nil, nil)
	require.Equal(t, apperr.Missing, apperr.KindOf(err))
}

func TestListScopesRejectsUntrustedCallersBeforeDatabase(t *testing.T) {
	store := Store{}
	for _, principal := range []identity.Principal{
		{}, {Service: "ingest"}, {Service: "gateway", Gateway: true},
		{Service: "workspace", ActorID: uuid.New(), ActorKind: identity.User},
		{Service: "leta", ActorID: uuid.New(), ActorKind: identity.Leta},
	} {
		ctx := identity.WithPrincipal(t.Context(), principal)
		_, err := store.ListScopes(ctx, uuid.New(), nil, nil)
		require.Equal(t, apperr.Forbidden, apperr.KindOf(err))
	}
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "workspace"})
	zero := int32(0)
	for _, test := range []struct {
		fs     uuid.UUID
		cursor *string
		limit  *int32
	}{
		{uuid.Nil, nil, nil}, {uuid.New(), nil, &zero},
		{uuid.New(), ptr("other|" + uuid.NewString()), nil},
	} {
		_, err := store.ListScopes(ctx, test.fs, test.cursor, test.limit)
		require.Equal(t, apperr.Invalid, apperr.KindOf(err))
	}
}
