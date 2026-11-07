//go:build integration

package grpc

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	temporal "github.com/qninhdt/openlet/apps/letfs/internal/temporal"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/worker"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func TestIntegrationStorageLifecycleOverAuthenticatedRPC(t *testing.T) {
	db := testfixture.Postgres(t, "../../../migrations/0001_initial.sql")
	tc, _ := sharedfixture.Temporal(t)
	store := &filesystem.Store{DB: db, MaxNodes: 100}
	jobs := &temporal.Jobs{Client: tc}
	service := &filesystem.Service{Store: store, Deletions: jobs}
	owner := worker.New(tc, temporal.Queue, worker.Options{WorkerStopTimeout: time.Second})
	temporal.Register(owner, &temporal.Activities{Store: store, Jobs: jobs})
	require.NoError(t, owner.Start())
	t.Cleanup(owner.Stop)
	const token = "isolated-storage-lifecycle-token-123456"
	const gateway = "isolated-storage-gateway-token-1234567"
	methods := []string{letfsv1.StorageAdministrationService_CreateFilesystem_FullMethodName, letfsv1.StorageAdministrationService_CreateScopes_FullMethodName, letfsv1.StorageAdministrationService_DeleteFilesystem_FullMethodName}
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{{Service: "workspace", Token: token, Methods: methods}, {Service: "gateway", Token: gateway, Gateway: true, Methods: methods}})
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	server := grpcgo.NewServer(grpcgo.UnaryInterceptor(authentication.Unary()))
	letfsv1.RegisterStorageAdministrationServiceServer(server, &Administration{Store: store, Service: service})
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	connection, err := grpcgo.NewClient(listener.Addr().String(), grpcgo.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	api := letfsv1.NewStorageAdministrationServiceClient(connection)
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	authorized := metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer "+token))
	fs := uuid.Must(uuid.NewV7()).String()
	input := &letfsv1.CreateFilesystemRequest{FilesystemId: fs, IdempotencyKey: uuid.NewString(), LimitBytes: 1024}
	_, err = api.CreateFilesystem(ctx, input)
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	public := metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer "+gateway, "x-openlet-account-id", uuid.NewString()))
	_, err = api.CreateFilesystem(public, input)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	created, err := api.CreateFilesystem(authorized, input)
	require.NoError(t, err)
	require.Equal(t, fs, created.Filesystem.Id)
	replayed, err := api.CreateFilesystem(authorized, input)
	require.NoError(t, err)
	require.Equal(t, created.Filesystem, replayed.Filesystem)
	var nodes int
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM nodes").Scan(&nodes))
	require.Zero(t, nodes, "filesystem provisioning has no business scope defaults")
	scopes := &letfsv1.CreateScopesRequest{FilesystemId: fs, IdempotencyKey: uuid.NewString(), ScopeIds: []string{uuid.Must(uuid.NewV7()).String(), uuid.Must(uuid.NewV7()).String()}}
	first, err := api.CreateScopes(authorized, scopes)
	require.NoError(t, err)
	again, err := api.CreateScopes(authorized, scopes)
	require.NoError(t, err)
	require.Equal(t, first, again)
	require.Len(t, first.Scopes, 2)
	require.NotEmpty(t, first.Scopes[0].RootId)
	require.True(t, first.Scopes[0].AllowBlobFiles)
	require.True(t, first.Scopes[0].AllowIndexing)
	disabled := false
	restricted, err := api.CreateScopes(authorized, &letfsv1.CreateScopesRequest{FilesystemId: fs, IdempotencyKey: uuid.NewString(), ScopeIds: []string{uuid.Must(uuid.NewV7()).String()}, AllowBlobFiles: &disabled, AllowIndexing: &disabled})
	require.NoError(t, err)
	require.False(t, restricted.Scopes[0].AllowBlobFiles)
	require.False(t, restricted.Scopes[0].AllowIndexing)
	deletion, err := api.DeleteFilesystem(authorized, &letfsv1.DeleteFilesystemRequest{FilesystemId: fs})
	require.NoError(t, err)
	require.False(t, deletion.Completed)
	require.Eventually(t, func() bool {
		var state string
		return db.QueryRow(ctx, "SELECT state FROM filesystems WHERE id=$1", fs).Scan(&state) == nil && state == "deleted"
	}, 30*time.Second, 100*time.Millisecond)
	deletion, err = api.DeleteFilesystem(authorized, &letfsv1.DeleteFilesystemRequest{FilesystemId: fs})
	require.NoError(t, err)
	require.True(t, deletion.Completed)
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM nodes").Scan(&nodes))
	require.Zero(t, nodes)
}
