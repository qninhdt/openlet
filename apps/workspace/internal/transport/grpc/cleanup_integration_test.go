//go:build integration

package rpc

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	orchestration "github.com/qninhdt/openlet/apps/workspace/internal/temporal"
	localfixture "github.com/qninhdt/openlet/apps/workspace/internal/testfixture"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	letaclient "github.com/qninhdt/openlet/packages/go/clients/leta"
	letfsclient "github.com/qninhdt/openlet/packages/go/clients/letfs"
	letapb "github.com/qninhdt/openlet/packages/go/gen/openlet_api/leta/v1"
	pb "github.com/qninhdt/openlet/packages/go/gen/openlet_api/workspace/v1"
	sharedrpc "github.com/qninhdt/openlet/packages/go/rpc"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

// The Python process binds its real server before exposing its address to Go.
type cleanupLetaClient struct {
	client atomic.Pointer[letaclient.Client]
}

func (c *cleanupLetaClient) GetBinding(ctx context.Context, id uuid.UUID) (letaclient.Binding, error) {
	return c.client.Load().GetBinding(ctx, id)
}
func (c *cleanupLetaClient) ListWorkspaceLeta(ctx context.Context, id uuid.UUID, cursor *uuid.UUID) (letaclient.WorkspacePage, error) {
	return c.client.Load().ListWorkspaceLeta(ctx, id, cursor)
}
func (c *cleanupLetaClient) StopLetaForWorkspaceDeletion(ctx context.Context, ws, id uuid.UUID) error {
	return c.client.Load().StopLetaForWorkspaceDeletion(ctx, ws, id)
}

func TestIntegrationWorkspaceDeletionWaitsForNativeLetaCleanup(t *testing.T) {
	if os.Getenv("OPENLET_LETA_HITL_INTEGRATION") != "1" {
		t.Skip("set OPENLET_LETA_HITL_INTEGRATION=1 for the Python/Go cleanup journey")
	}
	ctx, cancel := context.WithTimeout(t.Context(), 3*time.Minute)
	defer cancel()
	db := testfixture.Postgres(t, localfixture.Path("apps", "workspace", "migrations", "0001_initial.sql"))
	graph, graphAddress, _ := testfixture.SpiceDB(t, localfixture.Path("packages", "contracts", "authz", "schema.zed"))
	tc, address := testfixture.Temporal(t)
	resources := &cleanupLetaClient{}
	service := &workspace.Service{Store: &workspace.Store{DB: db, Graph: graph, MaxMembers: 10}, Users: nativeUsers{}, Letas: resources}
	owner, creator, root, home := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	mapping := workspace.Creation{Input: workspace.CreateInput{ActorID: owner, Key: uuid.New(), Name: "Native cleanup"}, ID: uuid.New(), FilesystemID: uuid.New(), SharedScopeID: uuid.New(), PersonalScopeID: uuid.New()}
	_, err := service.SaveWorkspace(ctx, mapping)
	require.NoError(t, err)
	creatorPersonal := uuid.New()
	_, err = service.ApplyMembership(ctx, workspace.Mutation{Kind: "add", Key: uuid.New(), WorkspaceID: mapping.ID, ActorID: owner, TargetID: creator, Role: "member", PersonalScopeID: creatorPersonal})
	require.NoError(t, err)
	storage := &nativeStorage{scopes: []letfsclient.Scope{{ID: mapping.PersonalScopeID, FilesystemID: mapping.FilesystemID, RootID: uuid.New(), State: "active"}}}
	service.Storage, service.Homes = storage, storage
	service.Mutate = func(ctx context.Context, in workspace.Mutation) (workspace.Workspace, error) {
		return orchestration.Mutate(ctx, tc, in)
	}
	control := worker.New(tc, orchestration.Queue, worker.Options{WorkerStopTimeout: time.Second})
	control.RegisterWorkflow(orchestration.WorkspaceChanges)
	control.RegisterWorkflow(orchestration.DeleteWorkspace)
	control.RegisterActivity(&orchestration.Activities{Service: service, Letas: resources})
	require.NoError(t, control.Start())
	defer control.Stop()
	var storageCalls atomic.Int32
	fsWorker := worker.New(tc, shared.LetFSQueue, worker.Options{WorkerStopTimeout: time.Second})
	fsWorker.RegisterWorkflowWithOptions(func(workflow.Context, shared.FilesystemDeletion) error { storageCalls.Add(1); return nil }, workflow.RegisterOptions{Name: shared.DeleteFilesystemWorkflow})
	require.NoError(t, fsWorker.Start())
	defer fsWorker.Stop()
	auth, err := sharedrpc.NewAuthenticator([]sharedrpc.Credential{Credential(strings.Repeat("l", 32))})
	require.NoError(t, err)
	server, err := sharedrpc.NewServer(auth, sharedrpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	pb.RegisterWorkspaceServiceServer(server, &Server{Service: service, Ready: db.Ping})
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	stopped := make(chan error, 1)
	go func() { stopped <- server.Serve(listener) }()
	defer func() { server.Stop(); require.NoError(t, <-stopped) }()
	// Local test coordination only; all domain operations use production clients/Workflows.
	mux := http.NewServeMux()
	mux.HandleFunc("POST /bind", func(w http.ResponseWriter, r *http.Request) {
		var input struct {
			Address string `json:"address"`
		}
		if json.NewDecoder(r.Body).Decode(&input) != nil {
			w.WriteHeader(400)
			return
		}
		conn, e := sharedrpc.Dial(input.Address, strings.Repeat("w", 32), sharedrpc.Transport{AllowPlaintext: true})
		if e != nil {
			w.WriteHeader(500)
			return
		}
		t.Cleanup(func() { require.NoError(t, conn.Close()) })
		resources.client.Store(&letaclient.Client{API: letapb.NewLetaServiceClient(conn)})
		w.WriteHeader(204)
	})
	mux.HandleFunc("POST /delete", func(w http.ResponseWriter, r *http.Request) {
		_, e := orchestration.Mutate(ctx, tc, workspace.Mutation{Kind: "delete", WorkspaceID: mapping.ID, ActorID: owner, Key: uuid.New()})
		if e != nil {
			t.Log(e)
			w.WriteHeader(500)
			return
		}
		w.WriteHeader(204)
	})
	mux.HandleFunc("GET /state", func(w http.ResponseWriter, r *http.Request) {
		var status string
		if e := db.QueryRow(ctx, "SELECT status FROM workspaces WHERE id=$1", mapping.ID).Scan(&status); e != nil {
			w.WriteHeader(500)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"status": status, "storage_calls": storageCalls.Load()})
	})
	coordination := httptest.NewServer(mux)
	defer coordination.Close()
	fixture, err := json.Marshal(map[string]string{
		"address": listener.Addr().String(), "token": strings.Repeat("l", 32), "control": coordination.URL,
		"workspace_id": mapping.ID.String(), "leta_id": root.String(), "home_scope_id": home.String(),
		"owner_id": owner.String(), "creator_id": creator.String(), "personal_scope_id": mapping.PersonalScopeID.String(),
		"graph_address": graphAddress, "graph_key": testfixture.SpiceDBKey, "temporal_address": address,
	})
	require.NoError(t, err)
	command := exec.CommandContext(ctx, "uv", "run", "--locked", "--package", "leta", "pytest", "apps/leta/tests/integration/test_workspace_deletion.py", "-q", "--tb=short")
	command.Dir = localfixture.Path()
	command.Env = append(os.Environ(), "OPENLET_TEST_WORKSPACE_DELETION="+string(fixture))
	output, err := command.CombinedOutput()
	t.Log(string(output))
	require.NoError(t, err)
	require.EqualValues(t, 1, storageCalls.Load())
	require.NoError(t, tc.TerminateWorkflow(ctx, "workspace-changes/"+mapping.ID.String(), "", "test complete"))
}
