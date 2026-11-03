//go:build integration

package workspace

import (
	"context"
	"fmt"
	"io"
	"os"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
)

type cleaningClient struct {
	v1.PermissionsServiceClient
	remove func(context.Context, *v1.DeleteRelationshipsRequest) (*v1.DeleteRelationshipsResponse, error)
}

func (c cleaningClient) DeleteRelationships(ctx context.Context, request *v1.DeleteRelationshipsRequest, _ ...grpc.CallOption) (*v1.DeleteRelationshipsResponse, error) {
	return c.remove(ctx, request)
}

func TestIntegrationRelationshipCleanupPreservesPublishedAndForeignGroups(t *testing.T) {
	ctx := t.Context()
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	graph, address, _ := testfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	reader := testfixture.SpiceDBClient(t, address)
	data, err := os.ReadFile("../../../../packages/contracts/authz/roles.json")
	require.NoError(t, err)
	policy, err := authz.ParseRolePolicy(data)
	require.NoError(t, err)
	require.NoError(t, authz.InitializeRolePolicy(ctx, graph, policy))
	owner := uuid.New()
	created, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: owner, Key: uuid.New(), Name: "Cleanup"})
	require.NoError(t, err)
	id := created.ID
	storage := mapping(id)
	require.NoError(t, store.Activate(ctx, storage))
	require.NoError(t, store.SyncRelationships(ctx, graph, id))
	orphan, foreign := id.String()+"/0/failed/editor", uuid.NewString()+"/0/failed/editor"
	var updates []*v1.RelationshipUpdate
	// Member-only remnants must be found even if a lost cleanup response removed their role link.
	for i := range 1005 {
		updates = append(updates, graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "role_grant", orphan, "member", "user", fmt.Sprintf("abandoned-%d", i)))
	}
	updates = append(updates, graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "role_grant", foreign, "member", "user", "foreign"))
	for len(updates) > 0 {
		n := min(len(updates), 1000)
		_, err = graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: updates[:n]})
		require.NoError(t, err)
		updates = updates[n:]
	}
	require.NoError(t, store.CleanupRelationships(ctx, graph, id))
	require.NoError(t, store.CleanupRelationships(ctx, graph, id))
	read := func(group string) []*v1.Relationship {
		t.Helper()
		stream, err := reader.ReadRelationships(ctx, &v1.ReadRelationshipsRequest{
			Consistency:        &v1.Consistency{Requirement: &v1.Consistency_FullyConsistent{FullyConsistent: true}},
			RelationshipFilter: &v1.RelationshipFilter{ResourceType: "role_grant", OptionalResourceId: group},
		})
		require.NoError(t, err)
		var values []*v1.Relationship
		for {
			response, err := stream.Recv()
			if err == io.EOF {
				return values
			}
			require.NoError(t, err)
			values = append(values, response.Relationship)
		}
	}
	require.Empty(t, read(orphan))
	require.Len(t, read(foreign), 1)
	allowed, err := authz.Check(ctx, reader, owner.String(), authz.ContentWrite, authz.Resource{Type: "filesystem", ID: storage.FilesystemID.String()})
	require.NoError(t, err)
	require.True(t, allowed)

	// Publish a group after the cleanup scan, immediately before its native deletion.
	future, actor := id.String()+"/2/active/viewer", uuid.NewString()
	_, err = graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "role_grant", future, "role", "role", "viewer"),
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "role_grant", future, "member", "user", actor),
	}})
	require.NoError(t, err)
	published := false
	client := cleaningClient{PermissionsServiceClient: graph, remove: func(ctx context.Context, request *v1.DeleteRelationshipsRequest) (*v1.DeleteRelationshipsResponse, error) {
		if request.RelationshipFilter.OptionalResourceId == future && !published {
			_, err := graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{
				graphUpdate(v1.RelationshipUpdate_OPERATION_DELETE, "workspace", id.String(), "grant", "role_grant", id.String()+"/1/active/viewer"),
				graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "workspace", id.String(), "grant", "role_grant", future),
			}})
			if err != nil {
				return nil, err
			}
			published = true
		}
		return graph.DeleteRelationships(ctx, request)
	}}
	require.NoError(t, store.CleanupRelationships(ctx, client, id))
	require.True(t, published)
	require.Len(t, read(future), 2)
	allowed, err = authz.Check(ctx, reader, actor, authz.NodeRead, authz.Resource{Type: "filesystem", ID: storage.FilesystemID.String()})
	require.NoError(t, err)
	require.True(t, allowed, "native precondition protects a publication concurrent with cleanup")

	// A committed next revision can be staged without being published yet.
	_, err = store.DB.Exec(ctx, `UPDATE workspaces SET revision=revision+1 WHERE id=$1`, id)
	require.NoError(t, err)
	staged := id.String() + "/2/active/editor"
	_, err = graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "role_grant", staged, "role", "role", "editor"),
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "role_grant", staged, "member", "user", actor),
	}})
	require.NoError(t, err)
	require.NoError(t, store.CleanupRelationships(ctx, graph, id))
	require.Len(t, read(staged), 2, "canonical in-flight staging must survive cleanup before publication")
}
