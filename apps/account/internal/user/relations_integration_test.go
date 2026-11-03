//go:build integration

package user

import (
	"context"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"openlet/apps/account/internal/testfixture"
	"openlet/packages/go/authz"
	sharedfixture "openlet/packages/go/testfixture"
)

type recordingRelationshipWrites struct {
	v1.PermissionsServiceClient
	sizes []int
}

func (g *recordingRelationshipWrites) WriteRelationships(ctx context.Context, input *v1.WriteRelationshipsRequest, opts ...grpc.CallOption) (*v1.WriteRelationshipsResponse, error) {
	g.sizes = append(g.sizes, len(input.Updates))
	return g.PermissionsServiceClient.WriteRelationships(ctx, input, opts...)
}

func TestIntegrationAccountSelfRelationships(t *testing.T) {
	store := Store{DB: testfixture.Postgres(t)}
	graph, address, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	reader := sharedfixture.SpiceDBClient(t, address)
	ctx := t.Context()
	account, err := store.EnsureUser(ctx, "self-test")
	require.NoError(t, err)
	other, err := store.EnsureUser(ctx, "other-test")
	require.NoError(t, err)
	resource := authz.Resource{Type: "account", ID: account.UserID.String()}
	check := func(actor uuid.UUID, action authz.Action, want bool) {
		t.Helper()
		allowed, err := authz.Check(ctx, reader, actor.String(), action, resource)
		require.NoError(t, err)
		require.Equal(t, want, allowed)
	}
	check(account.UserID, authz.AccountRead, false)
	require.NoError(t, store.SyncRelationships(ctx, graph, account.UserID))
	require.NoError(t, store.SyncRelationships(ctx, graph, account.UserID))
	check(account.UserID, authz.AccountRead, true)
	check(account.UserID, authz.AccountUpdate, true)
	check(other.UserID, authz.AccountRead, false)
	check(other.UserID, authz.AccountUpdate, false)
	_, err = store.Profile(ctx, account.UserID)
	require.EqualError(t, err, "NOT_FOUND", "self relationship cannot bypass onboarding lifecycle")
	require.EqualError(t, store.SyncRelationships(ctx, graph, uuid.Nil), "VALIDATION")
	missing := uuid.New()
	require.EqualError(t, store.SyncRelationships(ctx, graph, missing), "NOT_FOUND")
	allowed, err := authz.Check(ctx, reader, missing.String(), authz.AccountRead, authz.Resource{Type: "account", ID: missing.String()})
	require.NoError(t, err)
	require.False(t, allowed)
	_, err = graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "account"}})
	require.NoError(t, err)
	check(account.UserID, authz.AccountRead, false)
	require.NoError(t, store.SyncRelationships(ctx, graph, account.UserID))
	check(account.UserID, authz.AccountRead, true)

	_, err = store.DB.Exec(ctx, `INSERT INTO users(id,clerk_id,status) SELECT ('00000000-0000-4000-8000-'||lpad(i::text,12,'0'))::uuid,'scan-'||i,'failed' FROM generate_series(1,101) AS i`)
	require.NoError(t, err)
	first, err := store.RelationshipIDs(ctx, uuid.Nil)
	require.NoError(t, err)
	require.Len(t, first, 100)
	require.Equal(t, uuid.MustParse("00000000-0000-4000-8000-000000000001"), first[0])
	require.Equal(t, uuid.MustParse("00000000-0000-4000-8000-000000000100"), first[99])
	next, err := store.RelationshipIDs(ctx, first[99])
	require.NoError(t, err)
	require.Len(t, next, 3, "scan must include failed identities and existing provisioning identities")
	require.Equal(t, uuid.MustParse("00000000-0000-4000-8000-000000000101"), next[0])
	require.Contains(t, next, account.UserID)
	require.Contains(t, next, other.UserID)
	last, err := store.RelationshipIDs(ctx, next[len(next)-1])
	require.NoError(t, err)
	require.Empty(t, last)
	recorder := &recordingRelationshipWrites{PermissionsServiceClient: graph}
	for _, ids := range [][]uuid.UUID{nil, {uuid.Nil}, {account.UserID, account.UserID}, make([]uuid.UUID, 101)} {
		require.EqualError(t, store.SyncRelationships(ctx, recorder, ids...), "VALIDATION")
	}
	require.EqualError(t, store.SyncRelationships(ctx, recorder, account.UserID, missing), "NOT_FOUND")
	require.Empty(t, recorder.sizes, "invalid or incomplete batches must not publish grants")
	require.NoError(t, store.RebuildRelationships(ctx, recorder))
	require.NoError(t, store.RebuildRelationships(ctx, recorder))
	require.Equal(t, []int{100, 3, 100, 3}, recorder.sizes, "each canonical page publishes once, including on retry")
	for _, id := range []uuid.UUID{first[0], first[99], next[0], next[len(next)-1]} {
		allowed, err := authz.Check(ctx, reader, id.String(), authz.AccountRead, authz.Resource{Type: "account", ID: id.String()})
		require.NoError(t, err)
		require.True(t, allowed, "rebuild must cross keyset pages, including nonactive identities")
	}
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	require.Error(t, store.RebuildRelationships(canceled, graph))
}
