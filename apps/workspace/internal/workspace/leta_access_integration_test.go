//go:build integration

package workspace

import (
	"context"
	"errors"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/authz"
	letaclient "github.com/qninhdt/openlet/packages/go/clients/leta"
	letfsclient "github.com/qninhdt/openlet/packages/go/clients/letfs"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
)

type homeStorageFunc func(context.Context, uuid.UUID, uuid.UUID, []uuid.UUID, bool, bool) ([]letfsclient.Scope, error)

func (f homeStorageFunc) CreateScopes(ctx context.Context, fs, key uuid.UUID, ids []uuid.UUID, blob, index bool) ([]letfsclient.Scope, error) {
	return f(ctx, fs, key, ids, blob, index)
}

type graphLosesReply struct {
	v1.PermissionsServiceClient
	lose bool
}

func (g *graphLosesReply) WriteRelationships(ctx context.Context, in *v1.WriteRelationshipsRequest, opts ...grpc.CallOption) (*v1.WriteRelationshipsResponse, error) {
	result, err := g.PermissionsServiceClient.WriteRelationships(ctx, in, opts...)
	if err == nil && g.lose {
		g.lose = false
		return nil, errors.New("write response lost")
	}
	return result, err
}

func TestIntegrationLetaHomePersonalGrantAndCleanup(t *testing.T) {
	ctx := t.Context()
	store := Store{DB: postgres(t), MaxMembers: 10}
	setupGraph(t, &store)
	service := Service{Store: &store, Users: scopeUsers{}}
	creator, resourceOwner, unrelated := uuid.New(), uuid.New(), uuid.New()
	in := creation(resourceOwner)
	_, err := service.SaveWorkspace(ctx, in)
	require.NoError(t, err)
	for _, user := range []uuid.UUID{creator, unrelated} {
		_, err = service.ApplyMembership(ctx, Mutation{Kind: "add", Key: uuid.New(), WorkspaceID: in.ID, ActorID: resourceOwner, TargetID: user, Role: "member", PersonalScopeID: uuid.New()})
		require.NoError(t, err)
	}
	root, home, homeRoot := uuid.New(), uuid.New(), uuid.New()
	binding := letaclient.Binding{LetaID: root, WorkspaceID: in.ID, CreatedByUserID: creator, HomeScopeID: home, Status: "initializing"}
	service.Letas = letaBindingFunc(func(_ context.Context, id uuid.UUID) (letaclient.Binding, error) {
		require.Equal(t, root, id)
		return binding, nil
	})
	homeInput := Mutation{Kind: "leta-home", WorkspaceID: in.ID, ActorID: creator, TargetID: root, ScopeID: home, Key: uuid.New()}
	service.Mutate = func(ctx context.Context, in Mutation) (Workspace, error) {
		if in.Kind == "leta-home" {
			return service.ProvisionLetaHome(ctx, in)
		}
		return service.UpdateScopeAccess(ctx, in)
	}
	storageCalls := 0
	service.Homes = homeStorageFunc(func(_ context.Context, fs, key uuid.UUID, ids []uuid.UUID, blob, index bool) ([]letfsclient.Scope, error) {
		storageCalls++
		require.Equal(t, in.FilesystemID, fs)
		require.Equal(t, homeInput.Key, key)
		require.Equal(t, []uuid.UUID{home}, ids)
		require.True(t, blob && index)
		return []letfsclient.Scope{{ID: home, FilesystemID: fs, RootID: homeRoot, State: "active", AllowBlobFiles: true, AllowIndexing: true}}, nil
	})
	_, err = service.EnsureLetaHomeAccess(ctx, homeInput)
	require.EqualError(t, err, "FORBIDDEN")
	require.Zero(t, storageCalls, "cannot publish defaults without canonical Leta-owned relations")
	_, err = store.Graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "leta", root.String(), "workspace", "workspace", in.ID.String()),
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "leta", root.String(), "creator", "user", creator.String()),
	}})
	require.NoError(t, err)
	lost := &graphLosesReply{PermissionsServiceClient: store.Graph, lose: true}
	store.Graph = lost
	_, err = service.EnsureLetaHomeAccess(ctx, homeInput)
	require.EqualError(t, err, "write response lost")
	_, err = service.EnsureLetaHomeAccess(ctx, homeInput)
	require.NoError(t, err)
	require.Equal(t, 2, storageCalls)
	_, err = store.DB.Exec(ctx, `UPDATE idempotency_keys SET expires_at=now()-interval '1 second' WHERE actor_id=$1 AND request_key=$2`, homeInput.ActorID, homeInput.Key)
	require.NoError(t, err)
	_, err = service.EnsureLetaHomeAccess(ctx, homeInput)
	require.NoError(t, err)
	require.Equal(t, 3, storageCalls, "expired request key still provisions the same reserved home identity")
	check := func(kind identity.ActorKind, actor, scope uuid.UUID, action authz.Action, want bool) {
		t.Helper()
		got, err := authz.Check(ctx, store.Graph, identity.Actor{Kind: kind, ID: actor}, action, authz.Resource{Type: "scope", ID: scope.String()})
		require.NoError(t, err)
		require.Equal(t, want, got)
	}
	check(identity.Leta, root, home, authz.ScopeWrite, true)
	check(identity.Leta, root, in.SharedScopeID, authz.ScopeWrite, true)
	check(identity.User, creator, home, authz.ScopeReadContent, true)
	check(identity.User, creator, home, authz.ScopeWrite, false)
	check(identity.User, resourceOwner, home, authz.ScopeReadContent, false)
	check(identity.Leta, root, in.PersonalScopeID, authz.ScopeReadContent, false)
	binding.Status = "active"
	resolved, err := service.ResolvePersonalScope(ctx, in.ID, root, resourceOwner)
	require.NoError(t, err)
	require.Equal(t, in.PersonalScopeID, resolved.ScopeID)
	require.Equal(t, resourceOwner, resolved.OwnerUserID)
	grant := Mutation{Kind: "scope", WorkspaceID: in.ID, ActorID: resourceOwner, TargetID: root, TargetKind: identity.Leta, ScopeID: resolved.ScopeID, ScopeRole: "viewer", PersonalOwnerID: resourceOwner, Key: uuid.New()}
	for _, actor := range []uuid.UUID{creator, unrelated} {
		bad := grant
		bad.ActorID = actor
		bad.PersonalOwnerID = actor
		_, err = service.ChangeTypedScopeAccess(ctx, bad)
		require.Error(t, err)
	}
	bad := grant
	bad.ScopeRole = "manager"
	_, err = service.ChangeTypedScopeAccess(ctx, bad)
	require.EqualError(t, err, "VALIDATION")
	bad = grant
	bad.ScopeID = in.SharedScopeID
	_, err = service.ChangeTypedScopeAccess(ctx, bad)
	require.Error(t, err)
	lost.lose = true
	_, err = service.ChangeTypedScopeAccess(ctx, grant)
	require.EqualError(t, err, "write response lost")
	check(identity.Leta, root, in.PersonalScopeID, authz.ScopeReadContent, true)
	check(identity.User, creator, in.PersonalScopeID, authz.ScopeReadContent, false)
	sufficient := grant
	sufficient.Key = uuid.New()
	_, err = service.ChangeTypedScopeAccess(ctx, sufficient)
	require.NoError(t, err)
	sufficient.ScopeRole = "editor"
	_, err = service.ChangeTypedScopeAccess(ctx, sufficient)
	require.EqualError(t, err, "IDEMPOTENCY_CONFLICT")
	// Recover the applied graph write before rejecting a now-deleting resource/workspace.
	binding.Status = "deleting"
	_, err = store.DB.Exec(ctx, `UPDATE workspaces SET status='deleting' WHERE id=$1`, in.ID)
	require.NoError(t, err)
	_, err = service.ChangeTypedScopeAccess(ctx, grant)
	require.NoError(t, err)
	changed := grant
	changed.ScopeRole = "editor"
	_, err = service.ChangeTypedScopeAccess(ctx, changed)
	require.EqualError(t, err, "IDEMPOTENCY_CONFLICT")
	queued := grant
	queued.Key = uuid.New()
	queued.ScopeRole = "editor"
	_, err = service.UpdateScopeAccess(ctx, queued)
	require.Error(t, err)
	check(identity.Leta, root, in.PersonalScopeID, authz.ScopeWrite, false)
	cleanup, err := service.CleanupWorkspace(ctx, in.ID, root)
	require.NoError(t, err)
	require.Empty(t, cleanup.Name)
	require.Empty(t, cleanup.Role)
	require.Equal(t, uuid.Nil, cleanup.PersonalScopeID)
	foreign := binding
	binding.WorkspaceID = uuid.New()
	_, err = service.CleanupWorkspace(ctx, in.ID, root)
	require.EqualError(t, err, "NOT_FOUND")
	binding = foreign
	// Cleanup must retain other root/user grants and home_of; it never joins the mutation queue.
	other := uuid.New()
	_, err = store.Graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "scope", in.PersonalScopeID.String(), "viewer", "leta", other.String()),
	}})
	require.NoError(t, err)
	service.Mutate = func(context.Context, Mutation) (Workspace, error) {
		t.Fatal("cleanup must not reenter WorkspaceChanges")
		return Workspace{}, nil
	}
	service.Storage = scopeStorageFunc(func(_ context.Context, fs uuid.UUID, limit int32, cursor *string) (letfsclient.ScopePage, error) {
		require.Equal(t, in.FilesystemID, fs)
		if cursor == nil {
			next := "second"
			return letfsclient.ScopePage{Items: []letfsclient.Scope{{ID: home}}, NextCursor: &next}, nil
		}
		require.Equal(t, "second", *cursor)
		return letfsclient.ScopePage{Items: []letfsclient.Scope{{ID: in.PersonalScopeID}, {ID: in.SharedScopeID}}}, nil
	})
	require.NoError(t, service.CleanupLetaAccess(ctx, in.ID, root, home, identity.Actor{}))
	require.NoError(t, service.CleanupLetaAccess(ctx, in.ID, root, home, identity.Actor{Kind: identity.User, ID: creator}))
	check(identity.Leta, root, in.PersonalScopeID, authz.ScopeReadContent, false)
	check(identity.Leta, root, home, authz.ScopeWrite, false)
	check(identity.Leta, other, in.PersonalScopeID, authz.ScopeReadContent, true)
	has, err := store.hasRelationship(ctx, "scope", home, "home_of", "leta", root)
	require.NoError(t, err)
	require.True(t, has)
	// Retained completion does not recreate access after cleanup.
	_, err = service.ChangeTypedScopeAccess(ctx, grant)
	require.NoError(t, err)
	check(identity.Leta, root, in.PersonalScopeID, authz.ScopeReadContent, false)
	_, err = store.DB.Exec(ctx, `UPDATE idempotency_keys SET expires_at=now()-interval '1 second' WHERE actor_id=$1 AND request_key=$2`, grant.ActorID, grant.Key)
	require.NoError(t, err)
	_, err = service.ChangeTypedScopeAccess(ctx, grant)
	require.EqualError(t, err, "WORKSPACE_DELETING", "expired completion cannot report historical success after access cleanup")
	_, err = store.DB.Exec(ctx, `UPDATE workspaces SET status='active' WHERE id=$1`, in.ID)
	require.NoError(t, err)
	_, err = service.CleanupWorkspace(ctx, in.ID, root)
	require.EqualError(t, err, "FORBIDDEN")
	require.EqualError(t, service.CleanupLetaAccess(ctx, in.ID, root, home, identity.Actor{}), "FORBIDDEN")
	require.EqualError(t, service.CleanupLetaAccess(ctx, in.ID, root, home, identity.Actor{Kind: identity.User, ID: resourceOwner}), "FORBIDDEN")
	require.NoError(t, service.CleanupLetaAccess(ctx, in.ID, root, home, identity.Actor{Kind: identity.User, ID: creator}))
	// An expired key is a new active request, not retained historical success.
	binding.Status = "active"
	service.Mutate = service.UpdateScopeAccess
	fresh := grant
	fresh.ScopeRole = "editor"
	_, err = service.ChangeTypedScopeAccess(ctx, fresh)
	require.NoError(t, err)
	check(identity.Leta, root, in.PersonalScopeID, authz.ScopeWrite, true)
	binding.Status = "deleting"
	_, err = service.ApplyMembership(ctx, Mutation{Kind: "member", Key: uuid.New(), WorkspaceID: in.ID, ActorID: creator, TargetID: creator, Remove: true})
	require.NoError(t, err)
	require.NoError(t, service.CleanupLetaAccess(ctx, in.ID, root, home, identity.Actor{Kind: identity.User, ID: creator}), "admitted archive cleanup survives creator departure")
	check(identity.Leta, root, in.PersonalScopeID, authz.ScopeWrite, false)
	_, err = store.DB.Exec(ctx, `UPDATE workspaces SET status='deleted' WHERE id=$1`, in.ID)
	require.NoError(t, err)
	service.Storage = scopeStorageFunc(func(context.Context, uuid.UUID, int32, *string) (letfsclient.ScopePage, error) {
		t.Fatal("deleted Workspace cleanup cannot enumerate a deleted filesystem")
		return letfsclient.ScopePage{}, nil
	})
	require.NoError(t, service.CleanupLetaAccess(ctx, in.ID, root, home, identity.Actor{}))
	require.EqualError(t, service.CleanupLetaAccess(ctx, in.ID, root, uuid.New(), identity.Actor{}), "FORBIDDEN")
	binding.Status = "archived"
	_, err = service.EnsureLetaHomeAccess(ctx, homeInput)
	require.EqualError(t, err, "STATE_CONFLICT")
}
