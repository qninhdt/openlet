//go:build integration

package grpc

import (
	"context"
	"net"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	letfsclient "github.com/qninhdt/openlet/packages/go/clients/letfs"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"github.com/stretchr/testify/require"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func TestIntegrationScopeCandidatesRequireActorFreeWorkspaceRPC(t *testing.T) {
	db := testfixture.Postgres(t, "../../../migrations/0001_initial.sql")
	store := &filesystem.Store{DB: db, MaxNodes: 100}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "workspace"})
	fs, scope := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: fs})
	require.NoError(t, err)
	scopes, err := store.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{scope}, false, true)
	require.NoError(t, err)
	const token = "isolated-scope-workspace-token-123456"
	const gateway = "isolated-scope-gateway-token-12345678"
	const ingest = "isolated-scope-ingest-token-123456789"
	method := letfsv1.StorageAdministrationService_ListScopes_FullMethodName
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{
		{Service: "workspace", Token: token, Methods: []string{method}},
		{Service: "gateway", Token: gateway, Gateway: true, Methods: []string{method}},
		{Service: "ingest", Token: ingest, Methods: []string{method}},
	})
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	server := grpcgo.NewServer(grpcgo.UnaryInterceptor(authentication.Unary()))
	letfsv1.RegisterStorageAdministrationServiceServer(server, &Administration{Store: store})
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	connection, err := grpcgo.NewClient(listener.Addr().String(), grpcgo.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	api := letfsv1.NewStorageAdministrationServiceClient(connection)
	input := &letfsv1.ListScopesRequest{FilesystemId: fs.String()}
	_, err = api.ListScopes(t.Context(), input)
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	for _, headers := range [][]string{
		{"authorization", "Bearer " + gateway, "x-openlet-user-id", uuid.NewString()},
		{"authorization", "Bearer " + token, "x-openlet-user-id", uuid.NewString()},
		{"authorization", "Bearer " + token, "x-openlet-leta-id", uuid.NewString()},
		{"authorization", "Bearer " + ingest},
	} {
		ctx := metadata.NewOutgoingContext(t.Context(), metadata.Pairs(headers...))
		_, err = api.ListScopes(ctx, input)
		require.Equal(t, codes.PermissionDenied, status.Code(err))
	}
	authorized := metadata.NewOutgoingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+token))
	listed, err := api.ListScopes(authorized, input)
	require.NoError(t, err)
	require.Len(t, listed.Scopes, 1)
	require.Equal(t, scopes[0].RootID.String(), listed.Scopes[0].RootId)
	require.False(t, listed.Scopes[0].AllowBlobFiles)
	require.True(t, listed.Scopes[0].AllowIndexing)
	client := letfsclient.Client{API: api}
	page, err := client.ListScopes(authorized, fs, 10, nil)
	require.NoError(t, err)
	require.Equal(t, scope, page.Items[0].ID)
	_, err = api.ListScopes(authorized, &letfsv1.ListScopesRequest{FilesystemId: "invalid"})
	require.Equal(t, codes.InvalidArgument, status.Code(err))
	ctx, cancel := context.WithCancel(authorized)
	cancel()
	_, err = api.ListScopes(ctx, input)
	require.Equal(t, codes.Canceled, status.Code(err))
}
