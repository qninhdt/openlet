//go:build integration

package testfixture

import (
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"openlet/packages/go/authz"
)

// Grant uses the production schema without introducing owner facts into the letfs database.
func Grant(t *testing.T, graph v1.PermissionsServiceClient, kind string, id, actor uuid.UUID, actions ...authz.Action) {
	t.Helper()
	group := kind + "/" + id.String() + "/" + actor.String()
	updates := []*v1.RelationshipUpdate{}
	touch := func(kind, id, relation, subjectKind, subject string) {
		updates = append(updates, &v1.RelationshipUpdate{Operation: v1.RelationshipUpdate_OPERATION_TOUCH,
			Relationship: &v1.Relationship{Resource: &v1.ObjectReference{ObjectType: kind, ObjectId: id}, Relation: relation,
				Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: subjectKind, ObjectId: subject}}}})
	}
	for _, action := range actions {
		touch("role", group, string(action), "user", "*")
	}
	touch("role_grant", group, "role", "role", group)
	touch("role_grant", group, "member", "user", actor.String())
	touch("workspace", group, "grant", "role_grant", group)
	touch("workspace", group, "enabled", "user", "*")
	touch(kind, id.String(), "workspace", "workspace", group)
	_, err := graph.WriteRelationships(t.Context(), &v1.WriteRelationshipsRequest{Updates: updates})
	require.NoError(t, err)
}
