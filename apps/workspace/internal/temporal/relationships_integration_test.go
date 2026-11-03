//go:build integration

package temporal

import (
	"context"
	"errors"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	sdktemporal "go.temporal.io/sdk/temporal"
	"google.golang.org/grpc"
	"os"
	"testing"
	"time"
)

type lostGraphResponse struct{ v1.PermissionsServiceClient }

func (g lostGraphResponse) WriteRelationships(ctx context.Context, in *v1.WriteRelationshipsRequest, opts ...grpc.CallOption) (*v1.WriteRelationshipsResponse, error) {
	_, err := g.PermissionsServiceClient.WriteRelationships(ctx, in, opts...)
	if err != nil {
		return nil, err
	}
	return nil, errors.New("graph acknowledgement lost")
}
func TestIntegrationMutationRecoversCommittedSQLAndLostGraphResponse(t *testing.T) {
	ctx := t.Context()
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := testfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	data, err := os.ReadFile("../../../../packages/contracts/authz/roles.json")
	require.NoError(t, err)
	policy, err := authz.ParseRolePolicy(data)
	require.NoError(t, err)
	require.NoError(t, authz.InitializeRolePolicy(ctx, graph, policy))
	store := &workspace.Store{DB: db, Graph: graph, MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	owner, member := uuid.New(), uuid.New()
	value, err := store.EnsureWorkspace(ctx, workspace.CreateInput{ActorID: owner, Key: uuid.New(), Name: "Retry"})
	require.NoError(t, err)
	storage := workspace.Storage{WorkspaceID: value.ID, BucketID: uuid.New(), FilesystemID: uuid.New(), RootID: uuid.New(), LimitBytes: "1024"}
	require.NoError(t, store.Activate(ctx, storage))
	_, err = db.Exec(ctx, `INSERT INTO workspace_members(workspace_id,user_id,role) VALUES($1,$2,'editor')`, value.ID, member)
	require.NoError(t, err)
	require.NoError(t, store.RebuildWorkspaceRelationships(ctx, graph, value.ID))
	a := &Activities{Store: store, Graph: graph}
	_, missingErr := a.PrepareMutation(ctx, Mutation{Kind: "update", WorkspaceID: uuid.New(), ActorID: owner, Key: uuid.New(), Update: workspace.UpdateInput{OwnerID: &member}})
	var rejected *sdktemporal.ApplicationError
	require.ErrorAs(t, missingErr, &rejected)
	require.True(t, rejected.NonRetryable())
	require.Equal(t, "NOT_FOUND", rejected.Type())

	current, err := store.Get(ctx, value.ID, owner)
	require.NoError(t, err)
	cmd := Mutation{Kind: "update", WorkspaceID: value.ID, ActorID: owner, Key: uuid.New(), Revision: current.Revision, Update: workspace.UpdateInput{OwnerID: &member}}
	prepared, err := a.PrepareMutation(ctx, cmd)
	require.NoError(t, err)
	// Simulate SQL commit followed by a lost Activity result. Its original precondition is now stale.
	receipt := workspace.MutationReceipt{Key: cmd.Key, Hash: workspace.Fingerprint(prepared)}
	_, err = store.Update(ctx, value.ID, owner, current.Revision, cmd.Update, receipt)
	require.NoError(t, err)
	a.Graph = lostGraphResponse{graph}
	_, err = a.ApplyMutation(ctx, prepared)
	require.EqualError(t, err, "graph acknowledgement lost")
	a.Graph = graph
	completed, err := a.ApplyMutation(ctx, prepared)
	require.NoError(t, err)
	require.NotEqual(t, current.Revision, completed.Revision)
	require.Equal(t, "editor", completed.Role)
	// A second delivery cannot repeat the owner transfer or increment the business revision.
	repeated, err := a.ApplyMutation(ctx, prepared)
	require.NoError(t, err)
	require.Equal(t, completed.Revision, repeated.Revision)
	for actor, want := range map[uuid.UUID]bool{owner: false, member: true} {
		allowed, err := authz.Check(ctx, graph, actor.String(), authz.WorkspaceTransfer, authz.Resource{Type: "workspace", ID: value.ID.String()})
		require.NoError(t, err)
		require.Equal(t, want, allowed)
	}
	var receipts int
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM idempotency_keys WHERE actor_id=$1 AND request_key=$2 AND expires_at IS NOT NULL`, owner, cmd.Key).Scan(&receipts))
	require.Equal(t, 1, receipts)
}
