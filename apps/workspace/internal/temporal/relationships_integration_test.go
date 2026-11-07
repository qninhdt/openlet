//go:build integration

package temporal

import (
	"context"
	"errors"
	"sync/atomic"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	localfixture "github.com/qninhdt/openlet/apps/workspace/internal/testfixture"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
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
func TestIntegrationCreationAndMembershipRequireGraphAcknowledgement(t *testing.T) {
	ctx := t.Context()
	db := testfixture.Postgres(t, localfixture.Path("apps", "workspace", "migrations", "0001_initial.sql"))
	graph, _, _ := testfixture.SpiceDB(t, localfixture.Path("packages", "contracts", "authz", "schema.zed"))
	store := &workspace.Store{DB: db, Graph: lostGraphResponse{PermissionsServiceClient: graph}, MaxMembers: 10}
	service := &workspace.Service{Store: store}
	a := &Activities{Service: service}
	owner, member := uuid.New(), uuid.New()
	in := workspace.Creation{Input: workspace.CreateInput{ActorID: owner, Key: uuid.New(), Name: "Retry"}, ID: uuid.New(), FilesystemID: uuid.New(), SharedScopeID: uuid.New(), PersonalScopeID: uuid.New()}
	_, err := a.SaveWorkspace(ctx, in)
	require.Error(t, err)
	_, found, err := store.FindCreation(ctx, in.Input)
	require.NoError(t, err)
	require.False(t, found, "SQL commit alone must not acknowledge creation")
	store.Graph = graph
	first, err := a.SaveWorkspace(ctx, in)
	require.NoError(t, err)
	_, found, err = store.FindCreation(ctx, in.Input)
	require.NoError(t, err)
	require.True(t, found)
	store.Graph = lostGraphResponse{PermissionsServiceClient: graph}
	cmd := Mutation{Kind: "add", Key: uuid.New(), WorkspaceID: first.ID, ActorID: owner, TargetID: member, Role: "member", PersonalScopeID: uuid.New()}
	_, err = a.AddMember(ctx, cmd)
	require.Error(t, err)
	var completed bool
	require.NoError(t, db.QueryRow(ctx, "SELECT expires_at IS NOT NULL FROM idempotency_keys WHERE actor_id=$1 AND request_key=$2", owner, cmd.Key).Scan(&completed))
	require.False(t, completed)
	store.Graph = graph
	_, err = a.AddMember(ctx, cmd)
	require.NoError(t, err)
	_, err = a.AddMember(ctx, cmd)
	require.NoError(t, err)
	retained, err := store.Member(ctx, first.ID, member)
	require.NoError(t, err)
	require.Equal(t, cmd.PersonalScopeID, retained.PersonalScopeID)
	var count int
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM workspace_members WHERE workspace_id=$1", first.ID).Scan(&count))
	require.Equal(t, 2, count)
}

func TestIntegrationWorkspacePublicationSurvivesWorkerRestart(t *testing.T) {
	tc, _ := testfixture.Temporal(t)
	db := testfixture.Postgres(t, localfixture.Path("apps", "workspace", "migrations", "0001_initial.sql"))
	graph, _, _ := testfixture.SpiceDB(t, localfixture.Path("packages", "contracts", "authz", "schema.zed"))
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	committed := make(chan struct{}, 1)
	var filesystems, scopes, compensations atomic.Int32
	storage := worker.New(tc, shared.LetFSQueue, worker.Options{WorkerStopTimeout: time.Second})
	storage.RegisterActivityWithOptions(func(context.Context, shared.FilesystemCreation) error {
		filesystems.Add(1)
		return nil
	}, activity.RegisterOptions{Name: shared.CreateFilesystemActivity})
	storage.RegisterActivityWithOptions(func(context.Context, shared.ScopesCreation) error {
		scopes.Add(1)
		return nil
	}, activity.RegisterOptions{Name: shared.CreateScopesActivity})
	var current worker.Worker
	t.Cleanup(func() {
		if current != nil {
			current.Stop()
		}
	})
	start := func(lost bool) {
		if current != nil {
			current.Stop()
		}
		var permissions v1.PermissionsServiceClient = graph
		if lost {
			permissions = lostGraphResponse{graph, committed}
		}
		store := &workspace.Store{DB: db, Graph: permissions, MaxMembers: 10}
		current = worker.New(tc, Queue, worker.Options{WorkerStopTimeout: time.Second})
		current.RegisterWorkflow((&Workflows{QuotaLimit: 100}).CreateWorkspace)
		current.RegisterWorkflow(WorkspaceChanges)
		current.RegisterActivity(&Activities{Service: &workspace.Service{Store: store}})
		require.NoError(t, current.Start())
	}
	// Storage effects are external to this test; any compensating child is a regression.
	storage.RegisterWorkflowWithOptions(func(workflow.Context, shared.FilesystemDeletion) error {
		compensations.Add(1)
		return nil
	}, workflow.RegisterOptions{Name: shared.DeleteFilesystemWorkflow})
	storage.RegisterWorkflowWithOptions(func(workflow.Context, shared.ScopeDeletion) error {
		compensations.Add(1)
		return nil
	}, workflow.RegisterOptions{Name: shared.DeleteScopeWorkflow})
	require.NoError(t, storage.Start())
	t.Cleanup(storage.Stop)
	start(true)
	owner, member := uuid.New(), uuid.New()
	in := workspace.CreateInput{ActorID: owner, Key: uuid.New(), Name: "Retry"}
	run, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{TaskQueue: Queue}, shared.CreateWorkspaceWorkflow, in)
	require.NoError(t, err)
	select {
	case <-committed:
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	state, err := tc.DescribeWorkflowExecution(ctx, run.GetID(), run.GetRunID())
	require.NoError(t, err)
	require.Equal(t, enums.WORKFLOW_EXECUTION_STATUS_RUNNING, state.WorkflowExecutionInfo.Status)
	var fs, sharedScope uuid.UUID
	require.NoError(t, db.QueryRow(ctx, "SELECT filesystem_id,shared_scope_id FROM workspaces").Scan(&fs, &sharedScope))
	start(false)
	var result workspace.Workspace
	require.NoError(t, run.Get(ctx, &result))
	require.Equal(t, fs, result.FilesystemID)
	require.Equal(t, sharedScope, result.SharedScopeID)
	for len(committed) > 0 {
		<-committed
	}
	start(true)
	cmd := Mutation{Kind: "add", WorkspaceID: result.ID, FilesystemID: fs, ActorID: owner, TargetID: member, Role: "member", PersonalScopeID: uuid.Must(uuid.NewV7())}
	finished := make(chan error, 1)
	go func() { _, err := Mutate(ctx, tc, cmd); finished <- err }()
	select {
	case <-committed:
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	select {
	case err := <-finished:
		t.Fatalf("membership acknowledged before graph publication: %v", err)
	default:
	}
	start(false)
	require.NoError(t, <-finished)
	store := &workspace.Store{DB: db}
	retained, err := store.Member(ctx, result.ID, member)
	require.NoError(t, err)
	require.Equal(t, cmd.PersonalScopeID, retained.PersonalScopeID)
	var count int
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM workspace_members WHERE workspace_id=$1", result.ID).Scan(&count))
	require.Equal(t, 2, count)
	require.EqualValues(t, 1, filesystems.Load())
	require.EqualValues(t, 2, scopes.Load())
	require.Zero(t, compensations.Load())
}
