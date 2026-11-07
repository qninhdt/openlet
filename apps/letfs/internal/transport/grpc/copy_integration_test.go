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
	"github.com/qninhdt/openlet/packages/go/authz"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
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

func TestIntegrationCopyAndPurgeJobsOverAuthenticatedRPC(t *testing.T) {
	db := testfixture.Postgres(t, "../../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../../packages/contracts/authz/schema.zed")
	tc, _ := sharedfixture.Temporal(t)
	store := &filesystem.Store{DB: db, Graph: graph, MaxNodes: 100, MaxCopyNodes: 100, InlineLimit: 64, MaxFileBytes: 64,
		MaxOutstanding: 100, MaxCleanupBacklog: 100}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	actorContext := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	filesystemID, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: filesystemID, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := createTestScope(owner, store, uuid.New(), filesystemID, fs)
	require.NoError(t, err)

	testfixture.Grant(t, graph, "scope", fs, actor, authz.ScopeWrite, authz.ScopeReadMetadata, authz.ScopeWrite, authz.ScopeTrash, authz.ScopePurge)
	source, err := store.CreateNode(actorContext, fs, uuid.New(), filesystem.CreateNode{
		Parent: filesystem.Locator{NodeID: created.RootID}, Name: "source.bin", File: &filesystem.InlineFile{Content: []byte{0, 255, 1}, MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	const gatewayToken = "isolated-copy-gateway-token-123456789"
	methods := []string{letfsv1.FilesystemService_CreateCopy_FullMethodName,
		letfsv1.FilesystemService_PurgeTrash_FullMethodName}
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{{Service: "gateway", Token: gatewayToken, Gateway: true, Methods: methods}})
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	server := grpcgo.NewServer(grpcgo.UnaryInterceptor(authentication.Unary()))
	jobs := &temporal.Jobs{Client: tc}
	letfsv1.RegisterFilesystemServiceServer(server, &Filesystem{Store: store, Service: &filesystem.Service{Store: store, Processing: jobs, Copies: jobs, Deletions: jobs}})
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	connection, err := grpcgo.NewClient(listener.Addr().String(), grpcgo.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	api := letfsv1.NewFilesystemServiceClient(connection)
	deadline, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	public := metadata.NewOutgoingContext(deadline, metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-account-id", actor.String()))

	input := &letfsv1.CreateCopyRequest{FilesystemId: filesystemID.String(), ScopeId: fs.String(), SourceId: source.ID.String(), ParentId: created.RootID.String(),
		DestinationScopeId: fs.String(), Name: "copy.bin", Revision: &source.Revision, IdempotencyKey: uuid.NewString()}
	_, err = api.CreateCopy(deadline, input)
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	admitted, err := api.CreateCopy(public, input)
	require.NoError(t, err)
	replayed, err := api.CreateCopy(public, input)
	require.NoError(t, err)
	require.Equal(t, admitted.Copy.Id, replayed.Copy.Id)
	w := worker.New(tc, temporal.Queue, worker.Options{WorkerStopTimeout: time.Second})
	temporal.Register(w, &temporal.Activities{Store: store})
	require.NoError(t, w.Start())
	t.Cleanup(w.Stop)
	require.NoError(t, tc.GetWorkflow(deadline, "copy/"+filesystemID.String()+"/"+admitted.Copy.Id, "").Get(deadline, nil))
	other := uuid.New()
	foreign := metadata.NewOutgoingContext(deadline, metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-account-id", other.String()))
	copiedID := uuid.MustParse(admitted.Copy.DestinationRootId)
	copied, err := store.GetNode(actorContext, fs, filesystem.Locator{NodeID: &copiedID})
	require.NoError(t, err)
	entry, err := store.TrashNode(actorContext, fs, filesystem.Locator{NodeID: &copied.ID}, &copied.Revision)
	require.NoError(t, err)
	purge := &letfsv1.PurgeTrashRequest{FilesystemId: filesystemID.String(), ScopeId: fs.String(), EntryId: entry.ID.String()}
	_, err = api.PurgeTrash(foreign, purge)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	purging, err := api.PurgeTrash(public, purge)
	require.NoError(t, err)
	require.Equal(t, "purging", purging.Entry.Status)
	require.Eventually(t, func() bool {
		var exists bool
		err := db.QueryRow(deadline, "SELECT EXISTS(SELECT 1 FROM trash_entries WHERE id=$1)", entry.ID).Scan(&exists)
		return err == nil && !exists
	}, 30*time.Second, 100*time.Millisecond)
	absent, err := api.PurgeTrash(public, purge)
	require.NoError(t, err)
	require.Nil(t, absent.Entry)
	var used int64
	require.NoError(t, db.QueryRow(deadline, `SELECT used_bytes FROM filesystems WHERE id=$1`, filesystemID).Scan(&used))
	require.EqualValues(t, 3, used)
}
