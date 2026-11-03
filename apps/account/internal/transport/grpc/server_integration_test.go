//go:build integration

package rpc

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/account/internal/clients/clerk"
	"github.com/qninhdt/openlet/apps/account/internal/testfixture"
	"github.com/qninhdt/openlet/apps/account/internal/user"
	"github.com/qninhdt/openlet/packages/go/authz"
	accountv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/account/v1"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedrpc "github.com/qninhdt/openlet/packages/go/rpc"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func TestIntegrationAccountLookupsRequireWorkspaceService(t *testing.T) {
	db := testfixture.Postgres(t)
	store := &user.Store{DB: db}
	ctx := t.Context()
	active, err := store.EnsureUser(ctx, "trusted-active-subject")
	require.NoError(t, err)
	require.NoError(t, store.Complete(ctx, "trusted-active-subject", uuid.Must(uuid.NewV7())))
	name, avatar := "Việt Nam", "https://example.test/avatar.png"
	_, err = store.UpdateProfile(ctx, active.UserID, &name, &avatar)
	require.NoError(t, err)
	pending, err := store.EnsureUser(ctx, "pending-subject")
	require.NoError(t, err)

	var providerCalls atomic.Int32
	var providerUnavailable atomic.Bool
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		providerCalls.Add(1)
		assert.Equal(t, http.MethodGet, r.Method)
		assert.Equal(t, "/users/trusted-active-subject", r.URL.Path)
		assert.Equal(t, "Bearer isolated-clerk-key", r.Header.Get("Authorization"))
		if providerUnavailable.Load() {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"email_addresses":[{"email_address":"verified@example.test","verification":{"status":"verified"}},{"email_address":"unverified@example.test","verification":{"status":"unverified"}}]}`))
	}))
	t.Cleanup(provider.Close)
	schemaPath := testfixture.Path("packages", "contracts", "authz", "schema.zed")
	rolesPath := testfixture.Path("packages", "contracts", "authz", "roles.json")
	graph, _, _ := sharedfixture.SpiceDB(t, schemaPath)
	contract, err := authz.LoadContract(schemaPath, rolesPath)
	require.NoError(t, err)
	policy, err := os.ReadFile(rolesPath)
	require.NoError(t, err)
	roles, err := authz.ParseRolePolicy(policy)
	require.NoError(t, err)
	require.NoError(t, authz.InitializeRolePolicy(ctx, graph, roles))
	graphReady := func(ctx context.Context) error { return contract.Verify(ctx, graph, graph) }
	implementation := &Server{GraphReady: graphReady, Service: &user.Service{Store: store, Graph: graph, Clerk: clerk.Client{BaseURL: provider.URL, Secret: "isolated-clerk-key"}}}
	authenticator, err := sharedrpc.NewAuthenticator([]sharedrpc.Credential{
		{Service: "workspace", Token: strings.Repeat("w", 32), Methods: []string{
			accountv1.AccountService_GetUserSummaries_FullMethodName,
			accountv1.AccountService_GetVerifiedEmails_FullMethodName,
		}},
		{Service: "gateway", Gateway: true, Token: strings.Repeat("g", 32), Methods: []string{letfsv1.FilesystemService_GetNode_FullMethodName}},
	})
	require.NoError(t, err)
	server, err := sharedrpc.NewServer(authenticator, sharedrpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	accountv1.RegisterAccountServiceServer(server, implementation)
	healthv1.RegisterHealthServer(server, implementation)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	stopped := make(chan error, 1)
	go func() { stopped <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-stopped) })
	connect := func(token string) accountv1.AccountServiceClient {
		connection, err := sharedrpc.Dial(listener.Addr().String(), token, sharedrpc.Transport{AllowPlaintext: true})
		require.NoError(t, err)
		t.Cleanup(func() { require.NoError(t, connection.Close()) })
		return accountv1.NewAccountServiceClient(connection)
	}
	client := connect(strings.Repeat("w", 32))
	healthConnection, err := sharedrpc.Dial(listener.Addr().String(), strings.Repeat("w", 32), sharedrpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, healthConnection.Close()) })
	health, err := healthv1.NewHealthClient(healthConnection).Check(ctx, &healthv1.HealthCheckRequest{})
	require.NoError(t, err)
	require.Equal(t, healthv1.HealthCheckResponse_SERVING, health.Status)
	response, err := client.GetUserSummaries(ctx, &accountv1.GetUserSummariesRequest{Ids: []string{active.UserID.String(), pending.UserID.String(), uuid.NewString()}})
	require.NoError(t, err)
	require.Len(t, response.Users, 1, "only active users are exposed")
	require.Equal(t, active.UserID.String(), response.Users[0].Id)
	require.Equal(t, name, response.Users[0].DisplayName)
	require.Equal(t, avatar, response.Users[0].AvatarUrl)
	emails, err := client.GetVerifiedEmails(ctx, &accountv1.GetVerifiedEmailsRequest{UserId: active.UserID.String()})
	require.NoError(t, err)
	require.Equal(t, []string{"verified@example.test"}, emails.Emails)
	require.Equal(t, int32(1), providerCalls.Load())

	for _, ids := range [][]string{nil, {uuid.Nil.String()}, {"not-a-uuid"}, {active.UserID.String(), active.UserID.String()}, make([]string, 101)} {
		_, err := client.GetUserSummaries(ctx, &accountv1.GetUserSummariesRequest{Ids: ids})
		require.Equal(t, codes.InvalidArgument, status.Code(err))
	}
	for _, id := range []string{"", "malformed", uuid.Nil.String()} {
		_, err := client.GetVerifiedEmails(ctx, &accountv1.GetVerifiedEmailsRequest{UserId: id})
		require.Equal(t, codes.InvalidArgument, status.Code(err))
	}
	for _, id := range []string{pending.UserID.String(), uuid.NewString()} {
		_, err := client.GetVerifiedEmails(ctx, &accountv1.GetVerifiedEmailsRequest{UserId: id})
		require.Equal(t, codes.NotFound, status.Code(err))
	}
	require.Equal(t, int32(1), providerCalls.Load(), "invalid or inactive identities must not reach Clerk")
	for _, test := range []struct {
		token string
		code  codes.Code
	}{
		{strings.Repeat("x", 32), codes.Unauthenticated},
		{strings.Repeat("g", 32), codes.PermissionDenied},
	} {
		_, err := connect(test.token).GetVerifiedEmails(ctx, &accountv1.GetVerifiedEmailsRequest{UserId: active.UserID.String()})
		require.Equal(t, test.code, status.Code(err))
	}
	delegated := metadata.NewOutgoingContext(ctx, metadata.Pairs("x-openlet-user-id", active.UserID.String()))
	_, err = client.GetVerifiedEmails(delegated, &accountv1.GetVerifiedEmailsRequest{UserId: active.UserID.String()})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	require.Equal(t, int32(1), providerCalls.Load())

	providerUnavailable.Store(true)
	_, err = client.GetVerifiedEmails(ctx, &accountv1.GetVerifiedEmailsRequest{UserId: active.UserID.String()})
	require.Equal(t, codes.Unavailable, status.Code(err))
	require.NotContains(t, err.Error(), "isolated-clerk-key")
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	_, err = client.GetUserSummaries(canceled, &accountv1.GetUserSummariesRequest{Ids: []string{active.UserID.String()}})
	require.Equal(t, codes.Canceled, status.Code(err))

	for _, principal := range []identity.Principal{{}, {Service: "ingest"}, {Service: "workspace", Gateway: true}, {Service: "workspace", ActorID: active.UserID}} {
		_, err := implementation.GetUserSummaries(identity.WithPrincipal(ctx, principal), &accountv1.GetUserSummariesRequest{Ids: []string{active.UserID.String()}})
		require.Equal(t, codes.PermissionDenied, status.Code(err), "unverified in-process calls cannot bypass the operation boundary")
	}
	_, err = graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "role"}})
	require.NoError(t, err)
	health, err = healthv1.NewHealthClient(healthConnection).Check(ctx, &healthv1.HealthCheckRequest{})
	require.NoError(t, err)
	require.Equal(t, healthv1.HealthCheckResponse_NOT_SERVING, health.Status, "native readiness must detect policy drift")
	require.NoError(t, authz.InitializeRolePolicy(ctx, graph, roles))
	db.Close()
	health, err = healthv1.NewHealthClient(healthConnection).Check(ctx, &healthv1.HealthCheckRequest{})
	require.NoError(t, err)
	require.Equal(t, healthv1.HealthCheckResponse_NOT_SERVING, health.Status)
	_, err = client.GetUserSummaries(ctx, &accountv1.GetUserSummariesRequest{Ids: []string{active.UserID.String()}})
	require.Equal(t, codes.Unavailable, status.Code(err))
}
