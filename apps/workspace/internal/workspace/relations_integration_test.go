//go:build integration

package workspace

import (
	"context"
	"os"
	"sync"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"openlet/packages/go/authz"
	"openlet/packages/go/testfixture"
)

type publishingClient struct {
	v1.PermissionsServiceClient
	publish func(context.Context, *v1.WriteRelationshipsRequest) (*v1.WriteRelationshipsResponse, error)
}

func (c publishingClient) WriteRelationships(ctx context.Context, request *v1.WriteRelationshipsRequest, options ...grpc.CallOption) (*v1.WriteRelationshipsResponse, error) {
	if len(request.OptionalPreconditions) > 0 {
		return c.publish(ctx, request)
	}
	return c.PermissionsServiceClient.WriteRelationships(ctx, request, options...)
}

func TestIntegrationRelationshipSyncFencesOldGrantsAndLifecycle(t *testing.T) {
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	graph, address, _ := testfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	store.Graph = graph
	independent := testfixture.SpiceDBClient(t, address)
	data, err := os.ReadFile("../../../../packages/contracts/authz/roles.json")
	require.NoError(t, err)
	policy, err := authz.ParseRolePolicy(data)
	require.NoError(t, err)
	require.NoError(t, authz.InitializeRolePolicy(ctx, graph, policy))
	owner, member := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	created, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: owner, Key: uuid.Must(uuid.NewV7()), Name: "Team"}, "")
	require.NoError(t, err)
	id := created.Workspace.ID
	storage := mapping(id)
	require.NoError(t, store.Activate(ctx, storage))
	require.NoError(t, store.SyncRelationships(ctx, graph, id))
	_, token, err := store.Invite(ctx, id, owner, "member@example.com", "editor")
	require.NoError(t, err)
	_, err = store.AcceptInvite(ctx, member, token, []string{"member@example.com"})
	require.NoError(t, err)
	require.NoError(t, store.SyncRelationships(ctx, graph, id))
	check := func(actor uuid.UUID, action authz.Action, resource authz.Resource, want bool) {
		t.Helper()
		allowed, err := authz.Check(ctx, independent, actor.String(), action, resource)
		require.NoError(t, err)
		require.Equal(t, want, allowed, "%s %s", actor, action)
	}
	fs := authz.Resource{Type: "filesystem", ID: storage.FilesystemID.String()}
	ws := authz.Resource{Type: "workspace", ID: id.String()}
	check(member, authz.ContentWrite, fs, true)

	// Delay a real native write at the SDK boundary, after its old state was read/staged.
	delay := func() (func(), <-chan error) {
		t.Helper()
		entered, release, result := make(chan struct{}), make(chan struct{}), make(chan error, 1)
		var worker sync.WaitGroup
		worker.Go(func() {
			client := publishingClient{PermissionsServiceClient: graph, publish: func(ctx context.Context, request *v1.WriteRelationshipsRequest) (*v1.WriteRelationshipsResponse, error) {
				close(entered)
				select {
				case <-release:
					return graph.WriteRelationships(ctx, request)
				case <-ctx.Done():
					return nil, ctx.Err()
				}
			}}
			result <- store.SyncRelationships(ctx, client, id)
		})
		resume := sync.OnceFunc(func() { close(release) })
		t.Cleanup(func() { resume(); worker.Wait() })
		select {
		case <-entered:
		case <-ctx.Done():
			t.Fatal("old write never reached publication")
		}
		return resume, result
	}
	release, old := delay()
	current, err := store.Get(ctx, id, owner)
	require.NoError(t, err)
	require.NoError(t, store.ChangeMember(ctx, id, owner, member, "viewer", false, current.Revision))
	require.NoError(t, store.SyncRelationships(ctx, graph, id))
	check(member, authz.ContentWrite, fs, false)
	release()
	require.Equal(t, codes.FailedPrecondition, status.Code(<-old))
	check(member, authz.ContentWrite, fs, false)

	release, old = delay()
	current, err = store.Get(ctx, id, owner)
	require.NoError(t, err)
	_, err = store.Update(ctx, id, owner, current.Revision, UpdateInput{OwnerID: &member})
	require.NoError(t, err)
	require.NoError(t, store.SyncRelationships(ctx, graph, id))
	check(owner, authz.WorkspaceTransfer, ws, false)
	check(member, authz.WorkspaceTransfer, ws, true)
	release()
	require.Equal(t, codes.FailedPrecondition, status.Code(<-old))
	check(owner, authz.WorkspaceTransfer, ws, false)

	// Lost acknowledgment cannot turn retry into replay of the previous grant command.
	var ambiguous *v1.WriteRelationshipsRequest
	lost := publishingClient{PermissionsServiceClient: graph, publish: func(ctx context.Context, request *v1.WriteRelationshipsRequest) (*v1.WriteRelationshipsResponse, error) {
		_, err := graph.WriteRelationships(ctx, request)
		if err != nil {
			return nil, err
		}
		ambiguous = request
		return nil, status.Error(codes.DeadlineExceeded, "response lost")
	}}
	require.Equal(t, codes.DeadlineExceeded, status.Code(store.SyncRelationships(ctx, lost, id)))
	current, err = store.Get(ctx, id, member)
	require.NoError(t, err)
	require.NoError(t, store.ChangeMember(ctx, id, member, owner, "", true, current.Revision))
	require.NoError(t, store.SyncRelationships(ctx, graph, id))
	_, err = graph.WriteRelationships(ctx, ambiguous)
	require.Equal(t, codes.FailedPrecondition, status.Code(err))
	require.NoError(t, store.SyncRelationships(ctx, graph, id), "retry derives current SQL facts")
	check(owner, authz.NodeRead, fs, false)

	current, err = store.Get(ctx, id, member)
	require.NoError(t, err)
	_, err = store.BeginDeletion(ctx, DeleteInput{ActorID: member, WorkspaceID: id, Revision: current.Revision})
	require.NoError(t, err)
	require.NoError(t, store.SyncRelationships(ctx, graph, id))
	check(member, authz.NodeRead, fs, false)
	check(member, authz.WorkspaceRead, ws, true)
	release, old = delay()
	require.NoError(t, store.CompleteDeletion(ctx, id))
	require.NoError(t, store.SyncRelationships(ctx, graph, id))
	release()
	require.Equal(t, codes.FailedPrecondition, status.Code(<-old), "lifecycle identity also fences transitions without an existing revision increment")
	check(member, authz.NodeRead, fs, false)
	check(member, authz.WorkspaceRead, ws, true)
}

func TestIntegrationRelationshipSyncLargeMembershipAndFencedRebuild(t *testing.T) {
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 1200, QuotaLimit: 1024}
	graph, address, _ := testfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	independent := testfixture.SpiceDBClient(t, address)
	data, err := os.ReadFile("../../../../packages/contracts/authz/roles.json")
	require.NoError(t, err)
	policy, err := authz.ParseRolePolicy(data)
	require.NoError(t, err)
	require.NoError(t, authz.InitializeRolePolicy(ctx, graph, policy))
	owner := uuid.Must(uuid.NewV7())
	created, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: owner, Key: uuid.Must(uuid.NewV7()), Name: "Large"}, "")
	require.NoError(t, err)
	id := created.Workspace.ID
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
	client := publishingClient{PermissionsServiceClient: graph, publish: func(ctx context.Context, request *v1.WriteRelationshipsRequest) (*v1.WriteRelationshipsResponse, error) {
		allowed, err := authz.Check(ctx, independent, actor, authz.NodeRead, resource)
		require.NoError(t, err)
		require.False(t, allowed, "staged groups cannot expose partially populated membership")
		return graph.WriteRelationships(ctx, request)
	}}
	require.NoError(t, store.SyncRelationships(ctx, client, id), "large existing configured member limits do not exceed a native atomic write")
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
	require.NoError(t, store.SyncRelationships(ctx, graph, id))
	require.NoError(t, store.SyncRelationships(ctx, graph, id))
	allowed, err = authz.Check(ctx, independent, actor, authz.NodeRead, resource)
	require.NoError(t, err)
	require.True(t, allowed, "canonical business rows rebuild the projection without a ledger or epoch")
}
