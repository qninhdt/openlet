//go:build integration

package workspace

import (
	"github.com/qninhdt/openlet/packages/go/identity"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/stretchr/testify/require"
)

func TestIntegrationRebuildPreservesDirectScopeGrants(t *testing.T) {
	store := Store{DB: postgres(t), MaxMembers: 200}
	setupGraph(t, &store)
	ctx := t.Context()
	service := Service{Store: &store}
	owner, guest := uuid.New(), uuid.New()
	in := creation(owner)
	_, err := service.SaveWorkspace(ctx, in)
	require.NoError(t, err)
	_, err = store.Graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{
		graphUpdate(v1.RelationshipUpdate_OPERATION_DELETE, "scope", in.PersonalScopeID.String(), "manager", "user", owner.String()),
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "scope", in.PersonalScopeID.String(), "viewer", "user", guest.String()),
	}})
	require.NoError(t, err)
	var last uuid.UUID
	for range 101 {
		last = uuid.New()
		_, err = store.DB.Exec(ctx, "INSERT INTO workspace_members(workspace_id,user_id,role,personal_scope_id) VALUES($1,$2,'member',$3)", in.ID, last, uuid.New())
		require.NoError(t, err)
	}
	_, err = store.Graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: in.ID.String()}})
	require.NoError(t, err)
	require.NoError(t, store.RebuildRelationships(ctx, store.Graph))
	require.NoError(t, store.RebuildRelationships(ctx, store.Graph))
	for _, test := range []struct {
		actor, id uuid.UUID
		action    authz.Action
		want      bool
	}{
		{owner, in.PersonalScopeID, authz.ScopeManageAccess, false},
		{guest, in.PersonalScopeID, authz.ScopeReadContent, true},
		{last, in.SharedScopeID, authz.ScopeWrite, true},
	} {
		got, err := authz.Check(ctx, store.Graph, identity.Actor{Kind: identity.User, ID: test.actor}, test.action, authz.Resource{Type: "scope", ID: test.id.String()})
		require.NoError(t, err)
		require.Equal(t, test.want, got)
	}
}

func TestIntegrationScopeGrantCannotFollowWorkspaceDeletion(t *testing.T) {
	store := Store{DB: postgres(t), MaxMembers: 10}
	setupGraph(t, &store)
	ctx := t.Context()
	service := Service{Store: &store}
	in := creation(uuid.New())
	_, err := service.SaveWorkspace(ctx, in)
	require.NoError(t, err)
	for _, status := range []string{"active", "deleting", "deleted"} {
		t.Run(status, func(t *testing.T) {
			_, err := store.DB.Exec(ctx, `UPDATE workspaces SET status=$2 WHERE id=$1`, in.ID, status)
			require.NoError(t, err)
			target := uuid.New()
			_, err = service.UpdateScopeAccess(ctx, Mutation{TargetKind: identity.User, WorkspaceID: in.ID, ScopeID: in.SharedScopeID, TargetID: target, ScopeRole: "viewer"})
			if status == "active" {
				require.NoError(t, err)
			} else {
				require.EqualError(t, err, "WORKSPACE_DELETING")
			}
			allowed, err := authz.Check(ctx, store.Graph, identity.Actor{Kind: identity.User, ID: target}, authz.ScopeReadContent, authz.Resource{Type: "scope", ID: in.SharedScopeID.String()})
			require.NoError(t, err)
			require.Equal(t, status == "active", allowed)
		})
	}
}
