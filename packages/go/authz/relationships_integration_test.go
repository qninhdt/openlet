//go:build integration

package authz

import (
	"context"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	authzed "github.com/authzed/authzed-go/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"github.com/testcontainers/testcontainers-go"
)

func TestIntegrationHumanRolesAndLetaResourceAccess(t *testing.T) {
	client, address, server := graph(t)
	independent := connect(t, address)
	ctx := t.Context()
	creator := identity.Actor{Kind: identity.User, ID: uuid.New()}
	bot := identity.Actor{Kind: identity.Leta, ID: creator.ID}
	owner := identity.Actor{Kind: identity.User, ID: uuid.New()}
	admin := identity.Actor{Kind: identity.User, ID: uuid.New()}
	resourceOwner := identity.Actor{Kind: identity.User, ID: uuid.New()}
	shared := touch("scope", "shared", "editor", "workspace", "team")
	shared.Relationship.Subject.OptionalRelation = "member"
	write(t, client,
		touch("workspace", "team", "owner", "user", owner.ID.String()),
		touch("workspace", "team", "admin", "user", admin.ID.String()),
		touch("workspace", "team", "member", "user", creator.ID.String()),
		touch("workspace", "team", "member", "user", resourceOwner.ID.String()),
		touch("leta", bot.ID.String(), "workspace", "workspace", "team"),
		touch("leta", bot.ID.String(), "creator", "user", creator.ID.String()),
		touch("scope", "home", "home_of", "leta", bot.ID.String()),
		touch("scope", "home", "editor", "leta", bot.ID.String()),
		touch("scope", "shared", "editor", "leta", bot.ID.String()),
		touch("scope", "private", "manager", "user", resourceOwner.ID.String()),
		touch("scope", "private", "viewer", "leta", bot.ID.String()),
		touch("filesystem", "drive", "deleter", "user", owner.ID.String()),
		touch("filesystem", "drive", "reader", "leta", bot.ID.String()),
		shared,
	)
	for _, test := range []struct {
		actor    identity.Actor
		action   Action
		resource Resource
		want     bool
	}{
		{creator, LetaManage, Resource{"leta", bot.ID.String()}, true},
		{owner, LetaRead, Resource{"leta", bot.ID.String()}, false},
		{creator, ScopeReadContent, Resource{"scope", "home"}, true},
		{creator, ScopeReadContent, Resource{"scope", "private"}, false},
		{bot, ScopeReadContent, Resource{"scope", "private"}, true},
		{bot, ScopeWrite, Resource{"scope", "private"}, false},
		{bot, ScopeManageAccess, Resource{"scope", "home"}, false},
		{bot, ScopeWrite, Resource{"scope", "shared"}, true},
		{bot, WorkspaceDelete, Resource{"workspace", "team"}, false},
		{bot, WorkspaceCreateLeta, Resource{"workspace", "team"}, false},
		{creator, WorkspaceCreateLeta, Resource{"workspace", "team"}, true},
		{admin, WorkspaceManageMembers, Resource{"workspace", "team"}, true},
		{admin, WorkspaceDelete, Resource{"workspace", "team"}, false},
		{owner, FilesystemDelete, Resource{"filesystem", "drive"}, true},
		{bot, FilesystemRead, Resource{"filesystem", "drive"}, true},
		{bot, FilesystemDelete, Resource{"filesystem", "drive"}, false},
		{resourceOwner, ScopeManageAccess, Resource{"scope", "private"}, true},
	} {
		allowed, err := Check(ctx, independent, test.actor, test.action, test.resource)
		require.NoError(t, err)
		require.Equal(t, test.want, allowed, "%s %s %v", test.actor, test.action, test.resource)
	}
	write(t, client, remove("scope", "private", "viewer", "leta", bot.ID.String()))
	allowed, err := Check(ctx, independent, bot, ScopeReadContent, Resource{"scope", "private"})
	require.NoError(t, err)
	require.False(t, allowed, "revocation observes the current graph")
	write(t, client, remove("workspace", "team", "member", "user", creator.ID.String()))
	for _, resource := range []Resource{{"leta", bot.ID.String()}, {"scope", "home"}} {
		action := LetaRead
		if resource.Type == "scope" {
			action = ScopeReadContent
		}
		allowed, err = Check(ctx, independent, creator, action, resource)
		require.NoError(t, err)
		require.False(t, allowed, "creator membership gates resource/home visibility")
	}
	allowed, err = Check(ctx, independent, bot, ScopeWrite, Resource{"scope", "home"})
	require.NoError(t, err)
	require.True(t, allowed, "no unrequested departure-triggered runtime revocation")
	require.NoError(t, server.Stop(ctx, nil))
	checkCtx, cancel := context.WithTimeout(ctx, time.Second)
	defer cancel()
	allowed, err = Check(checkCtx, independent, bot, ScopeReadContent, Resource{"scope", "home"})
	require.Error(t, err)
	require.False(t, allowed)
}

func graph(t *testing.T) (*authzed.Client, string, testcontainers.Container) {
	t.Helper()
	return testfixture.SpiceDB(t, "../../contracts/authz/schema.zed")
}

func connect(t *testing.T, address string) *authzed.Client {
	t.Helper()
	return testfixture.SpiceDBClient(t, address)
}

func touch(rt, id, relation, st, subject string) *v1.RelationshipUpdate {
	return &v1.RelationshipUpdate{Operation: v1.RelationshipUpdate_OPERATION_TOUCH, Relationship: relationship(rt, id, relation, st, subject)}
}

func remove(rt, id, relation, st, subject string) *v1.RelationshipUpdate {
	return &v1.RelationshipUpdate{Operation: v1.RelationshipUpdate_OPERATION_DELETE, Relationship: relationship(rt, id, relation, st, subject)}
}

func write(t *testing.T, client *authzed.Client, updates ...*v1.RelationshipUpdate) {
	t.Helper()
	_, err := client.WriteRelationships(t.Context(), &v1.WriteRelationshipsRequest{Updates: updates})
	require.NoError(t, err)
}

func relationship(rt, id, relation, st, subject string) *v1.Relationship {
	return &v1.Relationship{Resource: &v1.ObjectReference{ObjectType: rt, ObjectId: id}, Relation: relation,
		Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: st, ObjectId: subject}}}
}
