//go:build integration

package workspace

import (
	"context"
	"errors"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"openlet/packages/go/authz"
)

func TestIntegrationRelationshipScanIncludesLifecycleTombstones(t *testing.T) {
	ctx := t.Context()
	store := Store{DB: postgres(t), MaxWorkspaces: 200, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	setupGraph(t, &store)
	owner := uuid.Must(uuid.NewV7())
	var ids []uuid.UUID
	for range 103 {
		created, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: owner, Key: uuid.Must(uuid.NewV7()), Name: "Scan"}, "")
		require.NoError(t, err)
		ids = append(ids, created.Workspace.ID)
	}
	require.NoError(t, store.Fail(ctx, ids[0]))
	require.NoError(t, store.Fail(ctx, ids[1]))
	syncGraph(t, &store, ids[1])
	value, err := store.Get(ctx, ids[1], owner)
	require.NoError(t, err)
	_, err = store.BeginDeletion(ctx, DeleteInput{WorkspaceID: value.ID, ActorID: owner, Revision: value.Revision})
	require.NoError(t, err)
	require.NoError(t, store.CompleteDeletion(ctx, value.ID))
	first, err := store.RelationshipIDs(ctx, uuid.Nil)
	require.NoError(t, err)
	require.Equal(t, ids[:100], first)
	next, err := store.RelationshipIDs(ctx, first[99])
	require.NoError(t, err)
	require.Equal(t, ids[100:], next)
	last, err := store.RelationshipIDs(ctx, next[2])
	require.NoError(t, err)
	require.Empty(t, last)
	for _, kind := range []string{"workspace", "role_grant"} {
		_, err = store.Graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: kind}})
		require.NoError(t, err)
	}
	publications := 0
	interrupted := publishingClient{PermissionsServiceClient: store.Graph, publish: func(ctx context.Context, request *v1.WriteRelationshipsRequest) (*v1.WriteRelationshipsResponse, error) {
		publications++
		if publications == 3 {
			return nil, errors.New("interrupted rebuild")
		}
		return store.Graph.WriteRelationships(ctx, request)
	}}
	require.EqualError(t, store.RebuildRelationships(ctx, interrupted), "interrupted rebuild")
	require.NoError(t, store.RebuildRelationships(ctx, store.Graph))
	require.NoError(t, store.RebuildRelationships(ctx, store.Graph))
	for _, id := range []uuid.UUID{ids[0], ids[1], ids[99], ids[102]} {
		allowed, err := authz.Check(ctx, store.Graph, owner.String(), authz.WorkspaceRead, authz.Resource{Type: "workspace", ID: id.String()})
		require.NoError(t, err)
		require.True(t, allowed, "rebuild must preserve status reads across pages and tombstones")
	}
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	require.Error(t, store.RebuildRelationships(canceled, store.Graph))
}
