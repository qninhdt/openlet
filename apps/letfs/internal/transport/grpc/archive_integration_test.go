//go:build integration

package grpc

import (
	"archive/zip"
	"bytes"
	"context"
	"io"
	"net"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"golang.org/x/sync/semaphore"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func TestIntegrationArchiveRPCFramesCancellationAndBlockedSendDeadline(t *testing.T) {
	db := testfixture.Postgres(t, "../../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../../packages/contracts/authz/schema.zed")
	store := &filesystem.Store{DB: db, Graph: graph, MaxNodes: 100, ArchiveSlots: semaphore.NewWeighted(1),
		Archive: filesystem.ArchiveConfig{MaxEntries: 10, MaxSourceBytes: 1000000, MaxOutputBytes: 2000000, Runtime: time.Second}}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	filesystemID, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: filesystemID, LimitBytes: 1000000})
	require.NoError(t, err)
	created, err := createTestScope(owner, store, uuid.New(), filesystemID, fs)
	require.NoError(t, err)
	file, actor := uuid.New(), uuid.New()
	payload := bytes.Repeat([]byte{0, 255, 9, 18}, 65536)
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'inline.bin','file',$4)`, file, fs, created.RootID, len(payload))
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes) VALUES($1,'inline',$2)`, file, payload)
	require.NoError(t, err)
	const token = "isolated-archive-gateway-token-123456"
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{{Service: "gateway", Token: token, Gateway: true, Methods: []string{letfsv1.FilesystemService_StreamArchive_FullMethodName}}})
	require.NoError(t, err)
	server, err := rpc.NewServer(authentication, rpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	letfsv1.RegisterFilesystemServiceServer(server, &Filesystem{Store: store, Service: &filesystem.Service{Store: store}})
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	connection, err := grpcgo.NewClient(listener.Addr().String(), grpcgo.WithTransportCredentials(insecure.NewCredentials()), grpcgo.WithStaticStreamWindowSize(65535), grpcgo.WithStaticConnWindowSize(65535))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	client := letfsv1.NewFilesystemServiceClient(connection)
	ctx := metadata.NewOutgoingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+token, "x-openlet-account-id", actor.String()))
	input := &letfsv1.StreamArchiveRequest{FilesystemId: filesystemID.String(), ScopeId: fs.String(), NodeId: created.RootID.String()}
	stream, err := client.StreamArchive(ctx, input)
	require.NoError(t, err)
	_, err = stream.Recv()
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	testfixture.Grant(t, graph, "scope", fs, actor, authz.ScopeReadContent)
	stream, err = client.StreamArchive(ctx, input)
	require.NoError(t, err)
	first, err := stream.Recv()
	require.NoError(t, err)
	require.Equal(t, "root.zip", first.GetMetadata().Filename)
	require.Equal(t, "application/zip", first.GetMetadata().Mime)
	var output bytes.Buffer
	for {
		frame, err := stream.Recv()
		if err == io.EOF {
			break
		}
		require.NoError(t, err)
		require.Nil(t, frame.GetMetadata())
		require.NotEmpty(t, frame.GetData())
		require.LessOrEqual(t, len(frame.GetData()), 65536)
		_, _ = output.Write(frame.GetData())
	}
	archive, err := zip.NewReader(bytes.NewReader(output.Bytes()), int64(output.Len()))
	require.NoError(t, err)
	require.Len(t, archive.File, 1)
	reader, err := archive.File[0].Open()
	require.NoError(t, err)
	content, err := io.ReadAll(reader)
	require.NoError(t, reader.Close())
	require.NoError(t, err)
	require.Equal(t, payload, content)
	permitReleased := func() bool {
		if !store.ArchiveSlots.TryAcquire(1) {
			return false
		}
		store.ArchiveSlots.Release(1)
		return true
	}
	require.Eventually(t, permitReleased, time.Second, 10*time.Millisecond)
	stream, err = client.StreamArchive(ctx, input)
	require.NoError(t, err)
	first, err = stream.Recv()
	require.NoError(t, err)
	require.NotNil(t, first.GetMetadata())
	// Stop reading so the real HTTP/2 flow-control window blocks the server's Send.
	require.Eventually(t, permitReleased, 3*time.Second, 10*time.Millisecond, "runtime deadline must release ZIP resources while Send is flow-controlled")
	for err == nil {
		_, err = stream.Recv()
	}
	require.Equal(t, codes.DeadlineExceeded, status.Code(err))
	cancelCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	stream, err = client.StreamArchive(cancelCtx, input)
	require.NoError(t, err)
	_, err = stream.Recv()
	require.NoError(t, err)
	cancel()
	for err == nil {
		_, err = stream.Recv()
	}
	require.Equal(t, codes.Canceled, status.Code(err))
	require.Eventually(t, permitReleased, time.Second, 10*time.Millisecond)
	store.Archive.MaxOutputBytes = 50
	stream, err = client.StreamArchive(ctx, input)
	require.NoError(t, err)
	first, err = stream.Recv()
	require.NoError(t, err)
	require.NotNil(t, first.GetMetadata())
	_, err = stream.Recv()
	require.Equal(t, codes.ResourceExhausted, status.Code(err), "a partial archive must end with non-OK status")
	require.Eventually(t, permitReleased, time.Second, 10*time.Millisecond)
}
