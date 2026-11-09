//go:build integration

package workspace

import (
	"context"
	"errors"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letaclient "github.com/qninhdt/openlet/packages/go/clients/leta"
	letfsclient "github.com/qninhdt/openlet/packages/go/clients/letfs"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
)

type scopeStorageFunc func(context.Context, uuid.UUID, int32, *string) (letfsclient.ScopePage, error)

func (f scopeStorageFunc) ListScopes(ctx context.Context, fs uuid.UUID, limit int32, cursor *string) (letfsclient.ScopePage, error) {
	return f(ctx, fs, limit, cursor)
}

type letaBindingFunc func(context.Context, uuid.UUID) (letaclient.Binding, error)

func (f letaBindingFunc) GetBinding(ctx context.Context, id uuid.UUID) (letaclient.Binding, error) {
	return f(ctx, id)
}

type scopeUsers struct{}

func (scopeUsers) Summaries(_ context.Context, ids []uuid.UUID) (map[uuid.UUID]UserSummary, error) {
	items := map[uuid.UUID]UserSummary{}
	for _, id := range ids {
		items[id] = UserSummary{ID: id, DisplayName: "Member"}
	}
	return items, nil
}

func (scopeUsers) VerifiedEmails(context.Context, uuid.UUID) ([]string, error) {
	panic("scope discovery must not resolve emails")
}

func TestIntegrationAccessibleScopesFiltersRightsAndPreservesContext(t *testing.T) {
	ctx := t.Context()
	store := Store{DB: postgres(t), MaxMembers: 10}
	setupGraph(t, &store)
	service := Service{Store: &store, Users: scopeUsers{}}
	in := creation(uuid.New())
	_, err := service.SaveWorkspace(ctx, in)
	require.NoError(t, err)
	creator, personal, admin := uuid.New(), uuid.New(), uuid.New()
	for user, role := range map[uuid.UUID]string{creator: "member", admin: "admin"} {
		scope := personal
		if user == admin {
			scope = uuid.New()
		}
		_, err = service.ApplyMembership(ctx, Mutation{Kind: "add", Key: uuid.New(), WorkspaceID: in.ID, ActorID: in.Input.ActorID, TargetID: user, Role: role, PersonalScopeID: scope})
		require.NoError(t, err)
	}
	// Equal UUIDs remain different authorization subjects.
	root, home := creator, uuid.New()
	binding := letaclient.Binding{LetaID: root, WorkspaceID: in.ID, CreatedByUserID: creator, HomeScopeID: home, Status: "active"}
	service.Letas = letaBindingFunc(func(_ context.Context, id uuid.UUID) (letaclient.Binding, error) {
		require.Equal(t, root, id)
		return binding, nil
	})
	updates := []*v1.RelationshipUpdate{
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "leta", root.String(), "workspace", "workspace", in.ID.String()),
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "leta", root.String(), "creator", "user", creator.String()),
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "scope", home.String(), "home_of", "leta", root.String()),
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "scope", home.String(), "editor", "leta", root.String()),
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "scope", in.SharedScopeID.String(), "editor", "leta", root.String()),
	}
	_, err = store.Graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: updates})
	require.NoError(t, err)
	denied, private := uuid.New(), in.PersonalScopeID
	ids := []uuid.UUID{denied, private, home, personal, in.SharedScopeID}
	roots := map[uuid.UUID]uuid.UUID{}
	for _, id := range ids {
		roots[id] = uuid.New()
	}
	storageCalls := 0
	service.Storage = scopeStorageFunc(func(_ context.Context, fs uuid.UUID, limit int32, cursor *string) (letfsclient.ScopePage, error) {
		storageCalls++
		require.Equal(t, in.FilesystemID, fs)
		start := 0
		if cursor != nil {
			for i, id := range ids {
				if id.String() == *cursor {
					start = i + 1
				}
			}
		}
		end := min(start+int(limit), len(ids))
		page := letfsclient.ScopePage{}
		for _, id := range ids[start:end] {
			page.Items = append(page.Items, letfsclient.Scope{ID: id, FilesystemID: fs, RootID: roots[id], State: "active"})
		}
		if end < len(ids) {
			next := ids[end-1].String()
			page.NextCursor = &next
		}
		return page, nil
	})
	human := identity.Actor{Kind: identity.User, ID: creator}
	agent := identity.Actor{Kind: identity.Leta, ID: root}
	page, err := service.AccessibleScopes(ctx, in.ID, human, creator, nil, 100)
	require.NoError(t, err)
	require.Len(t, page.Items, 3)
	require.Equal(t, home, page.Items[0].ID)
	require.False(t, page.Items[0].Write, "creator reads the agent home without a direct editor grant")
	require.Equal(t, "personal", page.Items[1].Kind)
	require.Equal(t, creator, page.Items[1].Owner.ID)
	require.True(t, page.Items[1].Write)
	page, err = service.AccessibleScopes(ctx, in.ID, agent, uuid.Nil, nil, 100)
	require.NoError(t, err)
	require.Len(t, page.Items, 2, "Leta does not inherit creator or workspace-owner personal scopes")
	require.Equal(t, "home", page.Items[0].Kind)
	require.Equal(t, home, page.Items[0].ID)
	require.True(t, page.Items[0].Write)
	require.Equal(t, "shared", page.Items[1].Kind)
	require.Nil(t, page.Items[1].Owner)
	_, err = service.AccessibleScopes(ctx, in.ID, agent, creator, nil, 100)
	require.NoError(t, err)
	before := storageCalls
	for _, inspector := range []uuid.UUID{admin, in.Input.ActorID} {
		_, err = service.AccessibleScopes(ctx, in.ID, agent, inspector, nil, 100)
		require.EqualError(t, err, "FORBIDDEN")
	}
	require.Equal(t, before, storageCalls, "denied inspectors never fetch storage metadata")

	first, err := service.AccessibleScopes(ctx, in.ID, agent, uuid.Nil, nil, 1)
	require.NoError(t, err)
	require.Empty(t, first.Items)
	require.NotNil(t, first.NextCursor)
	second, err := service.AccessibleScopes(ctx, in.ID, agent, uuid.Nil, first.NextCursor, 1)
	require.NoError(t, err)
	require.Empty(t, second.Items)
	require.NotEqual(t, first.NextCursor, second.NextCursor)
	third, err := service.AccessibleScopes(ctx, in.ID, agent, uuid.Nil, second.NextCursor, 1)
	require.NoError(t, err)
	require.Equal(t, home, third.Items[0].ID)
	for _, query := range []struct {
		subject   identity.Actor
		inspector uuid.UUID
	}{{human, creator}, {agent, creator}} {
		_, err = service.AccessibleScopes(ctx, in.ID, query.subject, query.inspector, first.NextCursor, 1)
		require.EqualError(t, err, "VALIDATION")
	}
	_, err = store.Graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "scope", private.String(), "viewer", "leta", root.String()),
	}})
	require.NoError(t, err)
	page, err = service.AccessibleScopes(ctx, in.ID, agent, uuid.Nil, nil, 100)
	require.NoError(t, err)
	require.Len(t, page.Items, 3)
	require.Equal(t, in.Input.ActorID, page.Items[0].Owner.ID)
	require.False(t, page.Items[0].Write)
	_, err = store.Graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{
		graphUpdate(v1.RelationshipUpdate_OPERATION_DELETE, "scope", private.String(), "viewer", "leta", root.String()),
	}})
	require.NoError(t, err)
	page, err = service.AccessibleScopes(ctx, in.ID, agent, uuid.Nil, nil, 100)
	require.NoError(t, err)
	require.Len(t, page.Items, 2, "fresh discovery observes a revoked grant")

	binding.WorkspaceID = uuid.New()
	_, err = service.AccessibleScopes(ctx, in.ID, agent, uuid.Nil, nil, 100)
	require.EqualError(t, err, "NOT_FOUND")
	binding.WorkspaceID, binding.Status = in.ID, "deleting"
	_, err = service.AccessibleScopes(ctx, in.ID, agent, uuid.Nil, nil, 100)
	require.EqualError(t, err, "STATE_CONFLICT")
	binding.Status = "active"
	_, err = service.ApplyMembership(ctx, Mutation{Kind: "member", Key: uuid.New(), WorkspaceID: in.ID, ActorID: creator, TargetID: creator, Remove: true})
	require.NoError(t, err)
	_, err = service.AccessibleScopes(ctx, in.ID, agent, creator, nil, 100)
	require.EqualError(t, err, "NOT_FOUND", "departed creator has no inspection bypass")
	_, err = service.AccessibleScopes(ctx, in.ID, agent, uuid.Nil, nil, 100)
	require.NoError(t, err, "creator departure does not invent a runtime lifecycle policy")
	service.Storage = scopeStorageFunc(func(context.Context, uuid.UUID, int32, *string) (letfsclient.ScopePage, error) {
		return letfsclient.ScopePage{}, errors.New("storage unavailable")
	})
	_, err = service.AccessibleScopes(ctx, in.ID, agent, uuid.Nil, nil, 100)
	require.ErrorContains(t, err, "storage unavailable")
	_, err = store.DB.Exec(ctx, "UPDATE workspaces SET status='deleting' WHERE id=$1", in.ID)
	require.NoError(t, err)
	_, err = service.AccessibleScopes(ctx, in.ID, agent, uuid.Nil, nil, 100)
	require.EqualError(t, err, "WORKSPACE_DELETING")
}

func TestAccessibleScopesRejectsInvalidSubjectsBeforeDependencies(t *testing.T) {
	service := Service{}
	for _, query := range []struct {
		subject   identity.Actor
		inspector uuid.UUID
		limit     int32
	}{
		{identity.Actor{}, uuid.Nil, 20},
		{identity.Actor{Kind: identity.User, ID: uuid.New()}, uuid.New(), 20},
		{identity.Actor{Kind: identity.Leta, ID: uuid.New()}, uuid.Nil, 0},
		{identity.Actor{Kind: identity.Leta, ID: uuid.New()}, uuid.Nil, 101},
	} {
		_, err := service.AccessibleScopes(t.Context(), uuid.New(), query.subject, query.inspector, nil, query.limit)
		require.Equal(t, apperr.Invalid, apperr.KindOf(err))
	}
}
