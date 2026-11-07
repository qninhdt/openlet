//go:build integration

package authz

import (
	"context"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	authzed "github.com/authzed/authzed-go/v1"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"github.com/testcontainers/testcontainers-go"
)

func TestIntegrationFixedRolesAndIndependentAccountAccess(t *testing.T) {
	client, address, server := graph(t)
	independent := connect(t, address)
	ctx := t.Context()
	shared := touch("scope", "shared", "editor", "workspace", "team")
	shared.Relationship.Subject.OptionalRelation = "member"
	write(t, client,
		touch("account", "agent", "self", "account", "agent"),
		touch("account", "agent", "owner", "account", "owner"),
		touch("workspace", "team", "owner", "account", "owner"),
		touch("workspace", "team", "admin", "account", "admin"),
		touch("workspace", "team", "member", "account", "agent"),
		shared,
		touch("scope", "private", "manager", "account", "agent"),
		touch("scope", "view", "viewer", "account", "viewer"),
		touch("filesystem", "drive", "deleter", "account", "owner"),
	)
	for _, test := range []struct {
		actor    string
		action   Action
		resource Resource
		want     bool
	}{
		{"owner", AccountUpdate, Resource{"account", "agent"}, true},
		{"owner", ScopeReadContent, Resource{"scope", "private"}, false},
		{"admin", ScopeReadContent, Resource{"scope", "private"}, false},
		{"agent", ScopeManageAccess, Resource{"scope", "private"}, true},
		{"agent", ScopeWrite, Resource{"scope", "shared"}, true},
		{"agent", WorkspaceDelete, Resource{"workspace", "team"}, false},
		{"admin", WorkspaceManageMembers, Resource{"workspace", "team"}, true},
		{"admin", WorkspaceDelete, Resource{"workspace", "team"}, false},
		{"owner", FilesystemDelete, Resource{"filesystem", "drive"}, true},
		{"owner", ScopeWrite, Resource{"scope", "shared"}, false},
		{"viewer", ScopeReadContent, Resource{"scope", "view"}, true},
		{"viewer", ScopeWrite, Resource{"scope", "view"}, false},
		{"viewer", ScopeReadMetadata, Resource{"scope", "private"}, false},
	} {
		allowed, err := Check(ctx, independent, test.actor, test.action, test.resource)
		require.NoError(t, err)
		require.Equal(t, test.want, allowed, "%s %s %v", test.actor, test.action, test.resource)
	}
	write(t, client, remove("workspace", "team", "member", "account", "agent"))
	allowed, err := Check(ctx, independent, "agent", ScopeWrite, Resource{"scope", "shared"})
	require.NoError(t, err)
	require.False(t, allowed, "fresh userset checks observe membership removal")
	allowed, err = Check(ctx, independent, "agent", ScopeManageAccess, Resource{"scope", "private"})
	require.NoError(t, err)
	require.True(t, allowed, "independent direct grants survive unrelated membership changes")
	require.NoError(t, server.Stop(ctx, nil))
	checkCtx, cancel := context.WithTimeout(ctx, time.Second)
	defer cancel()
	allowed, err = Check(checkCtx, independent, "agent", ScopeManageAccess, Resource{"scope", "private"})
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
