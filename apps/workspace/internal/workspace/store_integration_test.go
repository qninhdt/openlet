//go:build integration

package workspace

import (
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	localfixture "github.com/qninhdt/openlet/apps/workspace/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func postgres(t *testing.T) *pgxpool.Pool {
	return testfixture.Postgres(t, localfixture.Path("apps", "workspace", "migrations", "0001_initial.sql"))
}
func setupGraph(t *testing.T, store *Store) {
	t.Helper()
	graph, _, _ := testfixture.SpiceDB(t, localfixture.Path("packages", "contracts", "authz", "schema.zed"))
	store.Graph = graph
}
func creation(actor uuid.UUID) Creation {
	return Creation{Input: CreateInput{ActorID: actor, Key: uuid.New(), Name: "Team"}, ID: uuid.Must(uuid.NewV7()), FilesystemID: uuid.New(), SharedScopeID: uuid.New(), PersonalScopeID: uuid.New()}
}
func TestIntegrationWorkspaceMappingAndMemberLimit(t *testing.T) {
	store := Store{DB: postgres(t), MaxMembers: 2, InviteTTL: time.Hour}
	setupGraph(t, &store)
	service := Service{Store: &store}
	ctx := t.Context()
	owner := uuid.New()
	in := creation(owner)
	first, err := service.SaveWorkspace(ctx, in)
	require.NoError(t, err)
	again, err := service.SaveWorkspace(ctx, in)
	require.NoError(t, err)
	require.Equal(t, first, again)
	found, ok, err := store.FindCreation(ctx, in.Input)
	require.NoError(t, err)
	require.True(t, ok)
	require.Equal(t, first, found)
	// No workspace-count restriction: the same account can create another workspace.
	_, err = service.SaveWorkspace(ctx, creation(owner))
	require.NoError(t, err)
	start := make(chan struct{})
	results := make(chan error, 2)
	var workers sync.WaitGroup
	for range 2 {
		workers.Go(func() {
			<-start
			_, err := service.ApplyMembership(ctx, Mutation{Kind: "add", Key: uuid.New(), WorkspaceID: first.ID, ActorID: owner, TargetID: uuid.New(), Role: "member", PersonalScopeID: uuid.New()})
			results <- err
		})
	}
	close(start)
	workers.Wait()
	close(results)
	successes := 0
	for err := range results {
		if err == nil {
			successes++
		} else {
			require.EqualError(t, err, "RESOURCE_LIMIT")
		}
	}
	require.Equal(t, 1, successes)
	var count int
	require.NoError(t, store.DB.QueryRow(ctx, "SELECT count(*) FROM workspace_members WHERE workspace_id=$1 AND status='active'", first.ID).Scan(&count))
	require.Equal(t, 2, count)
}
