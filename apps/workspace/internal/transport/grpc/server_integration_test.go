//go:build integration

package rpc

import (
	"context"
	"encoding/json"
	"net"
	"os"
	"os/exec"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	localfixture "github.com/qninhdt/openlet/apps/workspace/internal/testfixture"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	letaclient "github.com/qninhdt/openlet/packages/go/clients/leta"
	letfsclient "github.com/qninhdt/openlet/packages/go/clients/letfs"
	workspaceclient "github.com/qninhdt/openlet/packages/go/clients/workspace"
	pb "github.com/qninhdt/openlet/packages/go/gen/openlet_api/workspace/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedrpc "github.com/qninhdt/openlet/packages/go/rpc"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

type nativeBindings struct {
	mu      sync.RWMutex
	binding letaclient.Binding
}

func (b *nativeBindings) GetBinding(_ context.Context, root uuid.UUID) (letaclient.Binding, error) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if root != b.binding.LetaID {
		return letaclient.Binding{}, workspace.Fault{Code: "NOT_FOUND"}
	}
	return b.binding, nil
}

func (b *nativeBindings) setStatus(status string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.binding.Status = status
}

type nativeStorage struct{ scopes []letfsclient.Scope }

func (s *nativeStorage) ListScopes(context.Context, uuid.UUID, int32, *string) (letfsclient.ScopePage, error) {
	return letfsclient.ScopePage{Items: s.scopes}, nil
}
func (s *nativeStorage) CreateScopes(_ context.Context, fs, key uuid.UUID, ids []uuid.UUID, blob, index bool) ([]letfsclient.Scope, error) {
	result := []letfsclient.Scope{}
	for _, id := range ids {
		result = append(result, letfsclient.Scope{ID: id, FilesystemID: fs, RootID: uuid.New(), State: "active", AllowBlobFiles: blob, AllowIndexing: index})
	}
	return result, nil
}

type nativeUsers struct{}

func (nativeUsers) Summaries(_ context.Context, ids []uuid.UUID) (map[uuid.UUID]workspace.UserSummary, error) {
	result := map[uuid.UUID]workspace.UserSummary{}
	for _, id := range ids {
		result[id] = workspace.UserSummary{ID: id, DisplayName: "Human"}
	}
	return result, nil
}
func (nativeUsers) VerifiedEmails(context.Context, uuid.UUID) ([]string, error) {
	panic("unexpected email lookup")
}

func TestIntegrationWorkspaceNativeReadsGrantsAndCleanup(t *testing.T) {
	ctx := t.Context()
	db := testfixture.Postgres(t, localfixture.Path("apps", "workspace", "migrations", "0001_initial.sql"))
	graph, graphAddress, _ := testfixture.SpiceDB(t, localfixture.Path("packages", "contracts", "authz", "schema.zed"))
	service := &workspace.Service{Store: &workspace.Store{DB: db, Graph: graph, MaxMembers: 10}, Users: nativeUsers{}}
	owner, creator, root, home := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	mapping := workspace.Creation{Input: workspace.CreateInput{ActorID: owner, Key: uuid.New(), Name: "Native team"}, ID: uuid.New(), FilesystemID: uuid.New(), SharedScopeID: uuid.New(), PersonalScopeID: uuid.New()}
	_, err := service.SaveWorkspace(ctx, mapping)
	require.NoError(t, err)
	creatorPersonal := uuid.New()
	_, err = service.ApplyMembership(ctx, workspace.Mutation{Kind: "add", Key: uuid.New(), WorkspaceID: mapping.ID, ActorID: owner, TargetID: creator, Role: "member", PersonalScopeID: creatorPersonal})
	require.NoError(t, err)
	binding := &nativeBindings{binding: letaclient.Binding{LetaID: root, WorkspaceID: mapping.ID, CreatedByUserID: creator, HomeScopeID: home, Status: "active"}}
	storage := &nativeStorage{scopes: []letfsclient.Scope{{ID: mapping.PersonalScopeID, FilesystemID: mapping.FilesystemID, RootID: uuid.New(), State: "active"}}}
	service.Letas, service.Storage, service.Homes = binding, storage, storage
	service.Mutate = func(ctx context.Context, in workspace.Mutation) (workspace.Workspace, error) {
		if in.Kind == "leta-home" {
			return service.ProvisionLetaHome(ctx, in)
		}
		return service.UpdateScopeAccess(ctx, in)
	}
	auth, err := sharedrpc.NewAuthenticator([]sharedrpc.Credential{Credential(strings.Repeat("l", 32))})
	require.NoError(t, err)
	server, err := sharedrpc.NewServer(auth, sharedrpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	implementation := &Server{Service: service, Ready: db.Ping}
	pb.RegisterWorkspaceServiceServer(server, implementation)
	healthv1.RegisterHealthServer(server, implementation)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	stopped := make(chan error, 1)
	go func() { stopped <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-stopped) })
	conn, err := sharedrpc.Dial(listener.Addr().String(), strings.Repeat("l", 32), sharedrpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, conn.Close()) })
	raw := pb.NewWorkspaceServiceClient(conn)
	client := workspaceclient.Client{API: raw}
	agent := identity.Actor{Kind: identity.Leta, ID: root}
	human := identity.Actor{Kind: identity.User, ID: owner}
	value, err := client.GetWorkspace(ctx, mapping.ID, agent)
	require.NoError(t, err)
	require.Nil(t, value.Role)
	require.Nil(t, value.PersonalScopeId)
	value, err = client.GetWorkspace(ctx, mapping.ID, human)
	require.NoError(t, err)
	require.Equal(t, "owner", value.GetRole())
	require.Equal(t, mapping.PersonalScopeID.String(), value.GetPersonalScopeId())
	members, err := client.ListMembers(ctx, mapping.ID, agent, 1, nil)
	require.NoError(t, err)
	require.Len(t, members.Items, 1)
	require.NotNil(t, members.NextCursor)
	members, err = client.ListMembers(ctx, mapping.ID, agent, 1, members.NextCursor)
	require.NoError(t, err)
	require.Len(t, members.Items, 1)
	require.Nil(t, members.NextCursor)
	scopes, err := client.ListAccessibleScopes(ctx, mapping.ID, agent, nil, 100, nil)
	require.NoError(t, err)
	require.Empty(t, scopes.Items)
	resolved, err := client.ResolvePersonalScope(ctx, mapping.ID, owner, agent)
	require.NoError(t, err)
	require.Equal(t, mapping.PersonalScopeID.String(), resolved.ScopeId)
	ownerString := owner.String()
	request := &pb.ChangeScopeAccessRequest{WorkspaceId: mapping.ID.String(), ScopeId: resolved.ScopeId, GranteeKind: "leta", GranteeId: root.String(), Role: "viewer", IdempotencyKey: uuid.NewString(), PersonalOwnerUserId: &ownerString}
	response, err := client.ChangeScopeAccess(ctx, human, request)
	require.NoError(t, err)
	require.True(t, response.Rights.ReadContent)
	require.False(t, response.Rights.Write)
	scopes, err = client.ListAccessibleScopes(ctx, mapping.ID, agent, nil, 100, nil)
	require.NoError(t, err)
	require.Len(t, scopes.Items, 1)
	require.Equal(t, owner.String(), scopes.Items[0].Owner.Id)
	// Exact service credentials and method-specific actor admission precede domain work.
	_, err = raw.GetWorkspace(ctx, &pb.GetWorkspaceRequest{WorkspaceId: mapping.ID.String()})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	delegated, err := sharedrpc.WithActor(ctx, agent)
	require.NoError(t, err)
	_, err = raw.ChangeScopeAccess(delegated, request)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	_, err = raw.ResolvePersonalScope(ctx, &pb.ResolvePersonalScopeRequest{WorkspaceId: mapping.ID.String(), OwnerUserId: owner.String()})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	duplicated := metadata.NewOutgoingContext(ctx, metadata.Pairs("x-openlet-user-id", owner.String(), "x-openlet-leta-id", root.String()))
	_, err = raw.ListMembers(duplicated, &pb.ListMembersRequest{WorkspaceId: mapping.ID.String(), Limit: 1})
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	wrong, err := sharedrpc.Dial(listener.Addr().String(), strings.Repeat("x", 32), sharedrpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, wrong.Close()) })
	_, err = pb.NewWorkspaceServiceClient(wrong).GetWorkspace(ctx, &pb.GetWorkspaceRequest{WorkspaceId: mapping.ID.String()})
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	health, err := healthv1.NewHealthClient(wrong).Check(ctx, &healthv1.HealthCheckRequest{})
	require.NoError(t, err)
	require.Equal(t, healthv1.HealthCheckResponse_SERVING, health.Status)
	_, err = client.GetCleanupWorkspace(ctx, mapping.ID, root)
	require.Error(t, err)
	// Home provisioning is refused while the canonical resource graph is missing.
	_, err = client.EnsureLetaHomeAccess(ctx, mapping.ID, root, home, uuid.New(), identity.Actor{Kind: identity.User, ID: creator})
	require.Error(t, err)
	binding.setStatus("deleting")
	_, err = db.Exec(ctx, `UPDATE workspaces SET status='deleting' WHERE id=$1`, mapping.ID)
	require.NoError(t, err)
	value, err = client.GetCleanupWorkspace(ctx, mapping.ID, root)
	require.NoError(t, err)
	require.Empty(t, value.Name)
	require.NoError(t, client.CleanupLetaAccess(ctx, mapping.ID, root, home, nil))
	// A completion response after cleanup reports current rights, without reapplying the grant.
	response, err = client.ChangeScopeAccess(ctx, human, request)
	require.NoError(t, err)
	require.False(t, response.Rights.ReadContent)
	_, err = client.GetWorkspace(ctx, mapping.ID, agent)
	require.Error(t, err)
	deadline, cancel := context.WithDeadline(ctx, time.Now().Add(-time.Second))
	defer cancel()
	_, err = raw.GetWorkspace(deadline, &pb.GetWorkspaceRequest{WorkspaceId: mapping.ID.String()})
	require.Equal(t, codes.DeadlineExceeded, status.Code(err))
	if os.Getenv("OPENLET_LETA_HITL_INTEGRATION") == "1" {
		_, err = db.Exec(ctx, `UPDATE workspaces SET status='active' WHERE id=$1`, mapping.ID)
		require.NoError(t, err)
		binding.setStatus("active")
		fixture, err := json.Marshal(map[string]string{
			"address": listener.Addr().String(), "token": strings.Repeat("l", 32),
			"workspace_id": mapping.ID.String(), "leta_id": root.String(), "home_scope_id": home.String(),
			"owner_id": owner.String(), "creator_id": creator.String(), "creator_personal_scope_id": creatorPersonal.String(),
			"personal_scope_id": mapping.PersonalScopeID.String(), "graph_address": graphAddress,
			"graph_key": testfixture.SpiceDBKey, "database_url": db.Config().ConnString(),
		})
		require.NoError(t, err)
		command := exec.CommandContext(ctx, "uv", "run", "--locked", "--package", "leta", "pytest", "apps/leta/tests/integration/test_human_workspace.py", "-q", "--tb=short")
		command.Dir = localfixture.Path()
		command.Env = append(os.Environ(), "OPENLET_TEST_HITL_WORKSPACE_FIXTURE="+string(fixture))
		output, err := command.CombinedOutput()
		t.Log(string(output))
		require.NoError(t, err)
	}
}
