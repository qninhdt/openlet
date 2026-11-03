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

func TestIntegrationRoleCapabilitiesAndInheritedFreshness(t *testing.T) {
	client, address, server := graph(t)
	independent := connect(t, address)
	ctx := t.Context()
	write(t, client,
		touch("role", "reader", "node_read", "user", "*"),
		touch("role", "editor", "node_read", "user", "*"),
		touch("role", "editor", "content_write", "user", "*"),
		touch("role", "owner", "node_read", "user", "*"),
		touch("role", "owner", "workspace_transfer", "user", "*"),
		touch("role_grant", "team-reader", "role", "role", "reader"),
		touch("role_grant", "team-reader", "member", "user", "viewer"),
		touch("role_grant", "team-editor", "role", "role", "editor"),
		touch("role_grant", "team-editor", "member", "user", "editor"),
		touch("role_grant", "team-owner", "role", "role", "owner"),
		touch("role_grant", "team-owner", "member", "user", "owner"),
		touch("workspace", "team", "grant", "role_grant", "team-reader"),
		touch("workspace", "team", "grant", "role_grant", "team-editor"),
		touch("workspace", "team", "grant", "role_grant", "team-owner"),
		touch("workspace", "team", "enabled", "user", "*"),
		touch("filesystem", "drive", "workspace", "workspace", "team"),
		touch("filesystem", "foreign", "workspace", "workspace", "other"),
	)
	for _, test := range []struct {
		actor    string
		action   Action
		resource Resource
		want     bool
	}{
		{"viewer", NodeRead, Resource{"filesystem", "drive"}, true},
		{"viewer", ContentWrite, Resource{"filesystem", "drive"}, false},
		{"editor", ContentWrite, Resource{"filesystem", "drive"}, true},
		{"editor", WorkspaceTransfer, Resource{"workspace", "team"}, false},
		{"owner", WorkspaceTransfer, Resource{"workspace", "team"}, true},
		{"owner", NodeRead, Resource{"filesystem", "foreign"}, false},
		{"viewer", BucketRead, Resource{"quota_bucket", "bucket"}, false},
	} {
		allowed, err := Check(ctx, independent, test.actor, test.action, test.resource)
		require.NoError(t, err)
		require.Equal(t, test.want, allowed, "%s %s %s", test.actor, test.action, test.resource.ID)
	}
	write(t, client, remove("role_grant", "team-reader", "member", "user", "viewer"))
	allowed, err := Check(ctx, independent, "viewer", NodeRead, Resource{"filesystem", "drive"})
	require.NoError(t, err)
	require.False(t, allowed, "fresh inherited check uses no returned token from the writer")

	write(t, client,
		remove("role_grant", "team-owner", "member", "user", "owner"),
		touch("role_grant", "team-owner", "member", "user", "editor"),
		touch("role_grant", "team-editor", "member", "user", "owner"),
		remove("role_grant", "team-editor", "member", "user", "editor"),
	)
	for actor, want := range map[string]bool{"owner": false, "editor": true} {
		allowed, err := Check(ctx, independent, actor, WorkspaceTransfer, Resource{"workspace", "team"})
		require.NoError(t, err)
		require.Equal(t, want, allowed)
	}
	require.NoError(t, server.Stop(ctx, nil))
	checkCtx, cancel := context.WithTimeout(ctx, time.Second)
	defer cancel()
	allowed, err = Check(checkCtx, independent, "editor", WorkspaceTransfer, Resource{"workspace", "team"})
	require.Error(t, err)
	require.False(t, allowed, "an outage must not reuse the previously granted permission")
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
