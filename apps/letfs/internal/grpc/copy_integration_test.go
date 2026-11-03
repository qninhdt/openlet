//go:build integration

package grpc

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/temporal"
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
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	tc, _ := testfixture.Temporal(t)
	store := &filesystem.Store{DB: db, Graph: graph, MaxNodes: 100, MaxCopyNodes: 100, InlineLimit: 64, MaxFileBytes: 64,
		MaxOutstanding: 100, MaxCleanupBacklog: 100}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	actorContext := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	bucket, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := store.CreateBucket(owner, uuid.New(), filesystem.CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	mounts := []filesystem.Mount{{Path: "/drive", FilesystemID: fs}}
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeCreate, authz.NodeRead, authz.CopyCreate, authz.NodeTrash, authz.TrashPurge)
	source, err := store.CreateNode(actorContext, fs, mounts, uuid.New(), filesystem.CreateNode{
		Parent: filesystem.Locator{NodeID: created.RootID}, Name: "source.bin", File: &filesystem.InlineFile{Content: []byte{0, 255, 1}, MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	const gatewayToken = "isolated-copy-gateway-token-123456789"
	methods := []string{letfsv1.FilesystemService_CreateCopy_FullMethodName, letfsv1.FilesystemService_GetCopy_FullMethodName,
		letfsv1.FilesystemService_PurgeTrash_FullMethodName}
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{{Service: "gateway", Token: gatewayToken, Gateway: true, Methods: methods}})
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	server := grpcgo.NewServer(grpcgo.UnaryInterceptor(authentication.Unary()))
	letfsv1.RegisterFilesystemServiceServer(server, &Filesystem{Store: store, Jobs: &temporal.Jobs{Client: tc}})
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	connection, err := grpcgo.NewClient(listener.Addr().String(), grpcgo.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	api := letfsv1.NewFilesystemServiceClient(connection)
	deadline, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	public := metadata.NewOutgoingContext(deadline, metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-user-id", actor.String()))
	paths := &letfsv1.PathContext{Mounts: []*letfsv1.Mount{{Path: "/drive", FilesystemId: fs.String()}}}
	input := &letfsv1.CreateCopyRequest{FilesystemId: fs.String(), SourceId: source.ID.String(), ParentId: created.RootID.String(),
		Name: "copy.bin", Revision: &source.Revision, IdempotencyKey: uuid.NewString(), PathContext: paths}
	_, err = api.CreateCopy(deadline, input)
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	admitted, err := api.CreateCopy(public, input)
	require.NoError(t, err)
	require.Equal(t, "accepted", admitted.Copy.Status)
	replayed, err := api.CreateCopy(public, input)
	require.NoError(t, err)
	require.Equal(t, admitted.Copy.Id, replayed.Copy.Id)
	statusInput := &letfsv1.GetCopyRequest{FilesystemId: fs.String(), CopyId: admitted.Copy.Id}
	_, err = api.GetCopy(public, statusInput)
	require.Equal(t, codes.PermissionDenied, status.Code(err), "copy_create does not grant copy_read")
	w := worker.New(tc, temporal.Queue, worker.Options{WorkerStopTimeout: time.Second})
	temporal.Register(w, &temporal.Activities{Store: store})
	require.NoError(t, w.Start())
	t.Cleanup(w.Stop)
	var result temporal.CopyState
	require.NoError(t, tc.GetWorkflow(deadline, "copy/"+fs.String()+"/"+admitted.Copy.Id, "").Get(deadline, &result))
	require.Equal(t, "succeeded", result.Status)
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.CopyRead)
	progress, err := api.GetCopy(public, statusInput)
	require.NoError(t, err)
	require.Equal(t, "succeeded", progress.Copy.Status)
	require.EqualValues(t, 1, progress.Copy.CommittedNodes)
	require.EqualValues(t, 3, progress.Copy.CommittedBytes)
	other := uuid.New()
	testfixture.Grant(t, graph, "filesystem", fs, other, authz.CopyRead)
	foreign := metadata.NewOutgoingContext(deadline, metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-user-id", other.String()))
	_, err = api.GetCopy(foreign, statusInput)
	require.Equal(t, codes.NotFound, status.Code(err), "copy_read alone cannot inspect another actor's job")
	testfixture.Grant(t, graph, "filesystem", fs, other, authz.CopyInspectAny)
	_, err = api.GetCopy(foreign, statusInput)
	require.NoError(t, err)
	copied, err := store.GetNode(actorContext, fs, mounts, filesystem.Locator{NodeID: &result.Admission.Root.Destination})
	require.NoError(t, err)
	entry, err := store.TrashNode(actorContext, fs, mounts, filesystem.Locator{NodeID: &copied.ID}, &copied.Revision)
	require.NoError(t, err)
	purge := &letfsv1.PurgeTrashRequest{FilesystemId: fs.String(), EntryId: entry.ID.String()}
	_, err = api.PurgeTrash(foreign, purge)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	purging, err := api.PurgeTrash(public, purge)
	require.NoError(t, err)
	require.Equal(t, "purging", purging.Entry.Status)
	var purged uuid.UUID
	require.NoError(t, tc.GetWorkflow(deadline, "purge-trash/"+fs.String()+"/"+entry.ID.String(), "").Get(deadline, &purged))
	require.Equal(t, entry.ID, purged)
	absent, err := api.PurgeTrash(public, purge)
	require.NoError(t, err)
	require.Nil(t, absent.Entry)
	var used int64
	require.NoError(t, db.QueryRow(deadline, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.EqualValues(t, 3, used)
}
