//go:build integration

package workspace

import (
	"context"
	"os"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	localfixture "github.com/qninhdt/openlet/apps/workspace/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
)

type publishingClient struct {
	v1.PermissionsServiceClient
	publish func(context.Context, *v1.WriteRelationshipsRequest) (*v1.WriteRelationshipsResponse, error)
}

func (c publishingClient) WriteRelationships(ctx context.Context, request *v1.WriteRelationshipsRequest, options ...grpc.CallOption) (*v1.WriteRelationshipsResponse, error) {
	return c.publish(ctx, request)
}

func TestIntegrationTargetedRelationshipsAndLifecycle(t *testing.T) {
	ctx := t.Context()
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	setupGraph(t, &store)
	graph := store.Graph
	owner, member, unrelated := uuid.New(), uuid.New(), uuid.New()
	created, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: owner, Key: uuid.New(), Name: "Team"})
	require.NoError(t, err)
	id := created.ID
	storage, err := store.ReserveStorage(ctx, id)
	require.NoError(t, err)
	storage.RootID = uuid.New()
	require.NoError(t, store.InitializeRelationships(ctx, graph, id))
	check := func(actor uuid.UUID, action authz.Action, resource authz.Resource, want bool) {
		t.Helper()
		allowed, err := authz.Check(ctx, graph, actor.String(), action, resource)
		require.NoError(t, err)
		require.Equal(t, want, allowed)
	}
	fs := authz.Resource{Type: "filesystem", ID: storage.FilesystemID.String()}
	ws := authz.Resource{Type: "workspace", ID: id.String()}
	check(owner, authz.WorkspaceRead, ws, true)
	check(owner, authz.ContentWrite, fs, false)
	require.NoError(t, store.PublishActivationRelationships(ctx, graph, id))
	require.NoError(t, store.Activate(ctx, storage))
	_, err = store.DB.Exec(ctx, `INSERT INTO workspace_members(workspace_id,user_id,role) VALUES($1,$2,'editor'),($1,$3,'viewer')`, id, member, unrelated)
	require.NoError(t, err)
	require.NoError(t, store.WriteMemberRelationships(ctx, graph, id, member, unrelated))
	check(member, authz.ContentWrite, fs, true)
	current, err := store.Get(ctx, id, owner)
	require.NoError(t, err)
	receipt := MutationReceipt{Key: uuid.New(), Hash: "change member"}
	require.NoError(t, store.ChangeMember(ctx, id, owner, member, "viewer", false, current.Revision, receipt))
	applied, err := store.MutationApplied(ctx, owner, id, receipt)
	require.NoError(t, err)
	require.True(t, applied)
	client := publishingClient{PermissionsServiceClient: graph, publish: func(ctx context.Context, r *v1.WriteRelationshipsRequest) (*v1.WriteRelationshipsResponse, error) {
		require.Len(t, r.Updates, 3)
		for _, u := range r.Updates {
			require.Equal(t, member.String(), u.Relationship.Subject.Object.ObjectId)
		}
		return graph.WriteRelationships(ctx, r)
	}}
	require.NoError(t, store.WriteMemberRelationships(ctx, client, id, member))
	require.NoError(t, store.WriteMemberRelationships(ctx, client, id, member))
	check(member, authz.ContentWrite, fs, false)
	check(unrelated, authz.NodeRead, fs, true)
	current, err = store.Get(ctx, id, owner)
	require.NoError(t, err)
	_, err = store.Update(ctx, id, owner, current.Revision, UpdateInput{OwnerID: &member}, MutationReceipt{})
	require.NoError(t, err)
	transfer := publishingClient{PermissionsServiceClient: graph, publish: func(ctx context.Context, r *v1.WriteRelationshipsRequest) (*v1.WriteRelationshipsResponse, error) {
		require.Len(t, r.Updates, 6)
		return graph.WriteRelationships(ctx, r)
	}}
	require.NoError(t, store.WriteMemberRelationships(ctx, transfer, id, owner, member))
	check(owner, authz.WorkspaceTransfer, ws, false)
	check(member, authz.WorkspaceTransfer, ws, true)
	current, err = store.Get(ctx, id, member)
	require.NoError(t, err)
	require.NoError(t, store.ChangeMember(ctx, id, member, owner, "", true, current.Revision, MutationReceipt{}))
	require.NoError(t, store.WriteMemberRelationships(ctx, graph, id, owner))
	check(owner, authz.NodeRead, fs, false)
	current, err = store.Get(ctx, id, member)
	require.NoError(t, err)
	_, err = store.BeginDeletion(ctx, DeleteInput{ActorID: member, WorkspaceID: id, Revision: current.Revision})
	require.NoError(t, err)
	require.NoError(t, store.PublishStorageRelationships(ctx, graph, id))
	check(member, authz.NodeRead, fs, false)
	check(member, authz.WorkspaceRead, ws, true)
	require.EqualError(t, store.PublishActivationRelationships(ctx, graph, id), "STATE_CONFLICT")
	require.NoError(t, store.CompleteDeletion(ctx, id))
	require.NoError(t, store.DeleteMemberRelationships(ctx, graph, id))
	check(unrelated, authz.WorkspaceRead, ws, false)
	check(member, authz.WorkspaceRead, ws, true)
}

func TestIntegrationOfflineRebuildPagesLargeMembership(t *testing.T) {
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 1200, QuotaLimit: 1024}
	graph, address, _ := testfixture.SpiceDB(t, localfixture.Path("packages", "contracts", "authz", "schema.zed"))
	independent := testfixture.SpiceDBClient(t, address)
	data, err := os.ReadFile(localfixture.Path("packages", "contracts", "authz", "roles.json"))
	require.NoError(t, err)
	policy, err := authz.ParseRolePolicy(data)
	require.NoError(t, err)
	require.NoError(t, authz.InitializeRolePolicy(ctx, graph, policy))
	owner := uuid.Must(uuid.NewV7())
	created, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: owner, Key: uuid.Must(uuid.NewV7()), Name: "Large"})
	require.NoError(t, err)
	id := created.ID
	storage := mapping(id)
	require.NoError(t, store.Activate(ctx, storage))
	var members [][]any
	for range 1001 {
		members = append(members, []any{id, uuid.Must(uuid.NewV7()), "viewer"})
	}
	tx, err := store.DB.Begin(ctx)
	require.NoError(t, err)
	defer tx.Rollback(ctx)
	_, err = tx.CopyFrom(ctx, pgx.Identifier{"workspace_members"}, []string{"workspace_id", "user_id", "role"}, pgx.CopyFromRows(members))
	require.NoError(t, err)
	_, err = tx.Exec(ctx, `UPDATE workspaces SET revision=revision+1 WHERE id=$1`, id)
	require.NoError(t, err)
	require.NoError(t, tx.Commit(ctx))
	store.MaxMembers = 10 // Lowering the admission limit cannot discard existing members during synchronization.
	actor := members[len(members)-1][1].(uuid.UUID).String()
	resource := authz.Resource{Type: "filesystem", ID: storage.FilesystemID.String()}
	require.NoError(t, store.RebuildWorkspaceRelationships(ctx, graph, id))
	allowed, err := authz.Check(ctx, independent, actor, authz.NodeRead, resource)
	require.NoError(t, err)
	require.True(t, allowed)

	// No writers run while the isolated projection is erased and rebuilt.
	for _, objectType := range []string{"workspace", "role_grant", "filesystem", "quota_bucket"} {
		_, err = graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: objectType}})
		require.NoError(t, err)
	}
	allowed, err = authz.Check(ctx, independent, actor, authz.NodeRead, resource)
	require.NoError(t, err)
	require.False(t, allowed)
	require.NoError(t, store.RebuildWorkspaceRelationships(ctx, graph, id))
	require.NoError(t, store.RebuildWorkspaceRelationships(ctx, graph, id))
	allowed, err = authz.Check(ctx, independent, actor, authz.NodeRead, resource)
	require.NoError(t, err)
	require.True(t, allowed, "canonical business rows rebuild the projection without a ledger or epoch")
}
