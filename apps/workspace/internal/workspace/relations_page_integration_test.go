//go:build integration

package workspace

import (
	"bytes"
	"context"
	"encoding/json"
	"github.com/qninhdt/openlet/packages/go/identity"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/stretchr/testify/require"
)

func TestIntegrationRelationshipScanIncludesLifecycleTombstones(t *testing.T) {
	ctx := t.Context()
	store := Store{DB: postgres(t), MaxMembers: 10}
	setupGraph(t, &store)
	service := Service{Store: &store}
	owner := uuid.Must(uuid.NewV7())
	var ids []uuid.UUID
	for range 103 {
		in := creation(owner)
		created, err := service.SaveWorkspace(ctx, in)
		require.NoError(t, err)
		ids = append(ids, created.ID)
	}
	_, err := service.MarkWorkspaceDeleting(ctx, DeleteInput{WorkspaceID: ids[0], ActorID: owner})
	require.NoError(t, err)
	_, err = service.MarkWorkspaceDeleting(ctx, DeleteInput{WorkspaceID: ids[1], ActorID: owner})
	require.NoError(t, err)
	require.NoError(t, service.RemoveWorkspace(ctx, ids[1]))
	first, err := store.RelationshipIDs(ctx, uuid.Nil)
	require.NoError(t, err)
	require.Equal(t, ids[:100], first)
	next, err := store.RelationshipIDs(ctx, first[99])
	require.NoError(t, err)
	require.Equal(t, ids[100:], next)
	last, err := store.RelationshipIDs(ctx, next[2])
	require.NoError(t, err)
	require.Empty(t, last)
	var inventory bytes.Buffer
	require.NoError(t, store.ExportResourceWorkspaces(ctx, &inventory))
	decoder := json.NewDecoder(&inventory)
	for index, id := range ids {
		var item struct {
			WorkspaceID uuid.UUID `json:"workspace_id"`
			Status      string    `json:"status"`
		}
		require.NoError(t, decoder.Decode(&item))
		require.Equal(t, id, item.WorkspaceID)
		expected := "active"
		if index == 0 {
			expected = "deleting"
		}
		if index == 1 {
			expected = "deleted"
		}
		require.Equal(t, expected, item.Status)
	}
	require.False(t, decoder.More())
	for _, kind := range []string{"workspace"} {
		_, err = store.Graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: kind}})
		require.NoError(t, err)
	}
	require.NoError(t, store.RebuildRelationships(ctx, store.Graph))
	require.NoError(t, store.RebuildRelationships(ctx, store.Graph))
	for _, id := range []uuid.UUID{ids[0], ids[1], ids[99], ids[102]} {
		allowed, err := authz.Check(ctx, store.Graph, identity.Actor{Kind: identity.User, ID: owner}, authz.WorkspaceRead, authz.Resource{Type: "workspace", ID: id.String()})
		require.NoError(t, err)
		require.Equal(t, id != ids[1], allowed, "deleted workspace grants stay revoked across rebuild pages")
	}
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	require.Error(t, store.RebuildRelationships(canceled, store.Graph))
}
