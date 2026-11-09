//go:build integration

package testfixture

import (
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/stretchr/testify/require"
)

// Grant uses the production schema without introducing owner facts into the letfs database.
func Grant(t *testing.T, graph v1.PermissionsServiceClient, kind string, id, actor uuid.UUID, actions ...authz.Action) {
	t.Helper()
	relation := "viewer"
	if kind == "filesystem" {
		relation = "reader"
	}
	for _, action := range actions {
		switch action {
		case authz.ScopeWrite, authz.ScopeTrash, authz.ScopeRestore:
			if relation != "manager" {
				relation = "editor"
			}
		case authz.ScopePurge, authz.ScopeManageAccess:
			relation = "manager"
		case authz.FilesystemDelete:
			relation = "deleter"
		}
	}
	_, err := graph.WriteRelationships(t.Context(), &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{{
		Operation: v1.RelationshipUpdate_OPERATION_TOUCH, Relationship: &v1.Relationship{
			Resource: &v1.ObjectReference{ObjectType: kind, ObjectId: id.String()}, Relation: relation,
			Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: "user", ObjectId: actor.String()}},
		},
	}}})
	require.NoError(t, err)
}
