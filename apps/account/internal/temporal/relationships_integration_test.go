//go:build integration

package temporal

import (
	"context"
	"errors"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/account/internal/account"
	localfixture "github.com/qninhdt/openlet/apps/account/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"
	"google.golang.org/grpc"
)

type lostGraphResponse struct {
	v1.PermissionsServiceClient
	committed chan struct{}
}

func (g lostGraphResponse) WriteRelationships(ctx context.Context, in *v1.WriteRelationshipsRequest, opts ...grpc.CallOption) (*v1.WriteRelationshipsResponse, error) {
	_, err := g.PermissionsServiceClient.WriteRelationships(ctx, in, opts...)
	if err != nil {
		return nil, err
	}
	select {
	case g.committed <- struct{}{}:
	default:
	}
	return nil, errors.New("graph acknowledgement lost")
}

func TestIntegrationManagedAccountPublicationSurvivesWorkerRestart(t *testing.T) {
	tc, _ := testfixture.Temporal(t)
	db := localfixture.Postgres(t)
	graph, _, _ := testfixture.SpiceDB(t, localfixture.Path("packages", "contracts", "authz", "schema.zed"))
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	store := &account.Store{DB: db}
	owner, err := store.EnsureAccount(ctx, "owner")
	require.NoError(t, err)
	in := account.ManagedCreation{ID: uuid.Must(uuid.NewV7()), OwnerID: owner, DisplayName: "Independent account"}
	committed := make(chan struct{}, 1)
	first := worker.New(tc, Queue, worker.Options{WorkerStopTimeout: time.Second})
	first.RegisterWorkflow(AccountChanges)
	first.RegisterActivity(&Activities{Service: &account.Service{Store: store, Graph: lostGraphResponse{graph, committed}}})
	require.NoError(t, first.Start())
	stopped := false
	t.Cleanup(func() {
		if !stopped {
			first.Stop()
		}
	})
	run, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{TaskQueue: Queue}, AccountChanges, in)
	require.NoError(t, err)
	select {
	case <-committed:
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	first.Stop()
	stopped = true
	state, err := tc.DescribeWorkflowExecution(ctx, run.GetID(), run.GetRunID())
	require.NoError(t, err)
	require.Equal(t, enums.WORKFLOW_EXECUTION_STATUS_RUNNING, state.WorkflowExecutionInfo.Status)
	retained, err := store.Profile(ctx, in.ID)
	require.NoError(t, err)
	require.Equal(t, &owner, retained.OwnerID)
	second := worker.New(tc, Queue, worker.Options{WorkerStopTimeout: time.Second})
	second.RegisterWorkflow(AccountChanges)
	second.RegisterActivity(&Activities{Service: &account.Service{Store: store, Graph: graph}})
	require.NoError(t, second.Start())
	t.Cleanup(second.Stop)
	var result account.Profile
	require.NoError(t, run.Get(ctx, &result))
	require.Equal(t, retained, result)
	var count int
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM accounts WHERE owner_id=$1", owner).Scan(&count))
	require.Equal(t, 1, count)
	allowed, err := authz.Check(ctx, graph, owner.String(), authz.AccountUpdate, authz.Resource{Type: "account", ID: result.ID.String()})
	require.NoError(t, err)
	require.True(t, allowed)
}
