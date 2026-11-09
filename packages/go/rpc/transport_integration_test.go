//go:build integration

package rpc

import (
	"archive/zip"
	"bytes"
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

const transportActor = "019a3b66-0000-7000-8000-000000000001"

var transportBytes = []byte{0, 255, 128, '\r', '\n', '<', 'x', '>', 0, 1}

// This fixture proves transport behavior, not the storage or permission implementation.
type transportFixture struct {
	letfsv1.UnimplementedFilesystemServiceServer
	slowStarted   chan struct{}
	slowStopped   chan struct{}
	streamStarted chan struct{}
	streamStopped chan struct{}
}

type archiveStreamWriter struct {
	stream grpc.ServerStreamingServer[letfsv1.StreamArchiveResponse]
}

func (w archiveStreamWriter) Write(data []byte) (int, error) {
	count := 0
	for len(data) > 0 {
		size := min(len(data), 65536)
		if err := w.stream.Send(&letfsv1.StreamArchiveResponse{Frame: &letfsv1.StreamArchiveResponse_Data{Data: data[:size]}}); err != nil {
			return count, err
		}
		count += size
		data = data[size:]
	}
	return count, nil
}

func (f *transportFixture) StreamArchive(r *letfsv1.StreamArchiveRequest, stream grpc.ServerStreamingServer[letfsv1.StreamArchiveResponse]) error {
	if err := f.admit(stream.Context(), r.FilesystemId); err != nil {
		return err
	}
	if err := stream.Send(&letfsv1.StreamArchiveResponse{Frame: &letfsv1.StreamArchiveResponse_Metadata{Metadata: &letfsv1.ArchiveMetadata{Filename: "report.zip", Mime: "application/zip"}}}); err != nil {
		return err
	}
	if r.NodeId == "failure" {
		return errors.New("signed-url=secret")
	}
	if r.NodeId == "slow" {
		close(f.streamStarted)
		defer close(f.streamStopped)
		chunk := make([]byte, 65536)
		for range 512 {
			if _, err := (archiveStreamWriter{stream}).Write(chunk); err != nil {
				return err
			}
		}
		return nil
	}
	archive := zip.NewWriter(archiveStreamWriter{stream})
	entry, err := archive.Create("report.bin")
	if err != nil {
		return err
	}
	if _, err = entry.Write(transportBytes); err != nil {
		return err
	}
	return archive.Close()
}

func (f *transportFixture) GetNode(ctx context.Context, r *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error) {
	if err := f.admit(ctx, r.FilesystemId); err != nil {
		return nil, err
	}
	if r.NodeId != "node" {
		return nil, Fault(codes.NotFound, "NOT_FOUND", "resource not found")
	}
	return &letfsv1.GetNodeResponse{Node: &letfsv1.Node{Id: "node", ScopeId: "drive", Name: "report.bin", Revision: 9223372036854775807}}, nil
}

func (f *transportFixture) admit(ctx context.Context, fs string) error {
	principal, ok := identity.FromContext(ctx)
	if !ok || principal.ActorID.String() != transportActor {
		return status.Error(codes.Unauthenticated, "verified actor required")
	}
	if fs != "drive" {
		return Fault(codes.NotFound, "NOT_FOUND", "resource not found")
	}
	return nil
}

func (f *transportFixture) GetDownload(ctx context.Context, r *letfsv1.GetDownloadRequest) (*letfsv1.GetDownloadResponse, error) {
	if err := f.admit(ctx, r.FilesystemId); err != nil {
		return nil, err
	}
	if r.NodeId == "slow" {
		close(f.slowStarted)
		<-ctx.Done()
		close(f.slowStopped)
		return nil, status.FromContextError(ctx.Err()).Err()
	}
	if r.NodeId != "node" {
		return nil, Fault(codes.NotFound, "NOT_FOUND", "resource not found")
	}
	download := &letfsv1.Download{Mime: "application/octet-stream", Filename: "report.bin", Etag: `"7"`, SizeBytes: int64(len(transportBytes)),
		Source: &letfsv1.Download_InlineContent{InlineContent: transportBytes}}
	return &letfsv1.GetDownloadResponse{Download: download}, nil
}

func transportServer(t *testing.T, address string) (*httptest.Server, *transportFixture) {
	t.Helper()
	f := &transportFixture{slowStarted: make(chan struct{}), slowStopped: make(chan struct{}), streamStarted: make(chan struct{}), streamStopped: make(chan struct{})}
	authentication, err := NewAuthenticator([]Credential{{Service: "gateway", Token: fixtureGateway, Gateway: true, Methods: []string{
		letfsv1.FilesystemService_GetNode_FullMethodName, letfsv1.FilesystemService_GetDownload_FullMethodName,
		letfsv1.FilesystemService_StreamArchive_FullMethodName,
	}}})
	require.NoError(t, err)
	server := grpc.NewServer(grpc.UnaryInterceptor(authentication.Unary()), grpc.StreamInterceptor(authentication.Stream()))
	letfsv1.RegisterFilesystemServiceServer(server, f)
	letfsv1.RegisterStorageAdministrationServiceServer(server, &letfsv1.UnimplementedStorageAdministrationServiceServer{})
	letfsv1.RegisterIngestServiceServer(server, &letfsv1.UnimplementedIngestServiceServer{})
	s := httptest.NewUnstartedServer(server)
	s.Config.Protocols = new(http.Protocols)
	s.Config.Protocols.SetUnencryptedHTTP2(true)
	require.NoError(t, s.Listener.Close())
	s.Listener, err = net.Listen("tcp", address)
	require.NoError(t, err)
	s.Start()
	_, port, err := net.SplitHostPort(s.Listener.Addr().String())
	require.NoError(t, err)
	s.URL = "http://127.0.0.1:" + port
	t.Cleanup(func() { server.Stop(); s.Close() })
	return s, f
}

func TestIntegrationNativeBytesAndCancellation(t *testing.T) {
	s, f := transportServer(t, "127.0.0.1:0")
	connection, err := grpc.NewClient(strings.TrimPrefix(s.URL, "http://"), grpc.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	client := letfsv1.NewFilesystemServiceClient(connection)
	ctx, deadline := context.WithTimeout(t.Context(), 5*time.Second)
	defer deadline()
	ctx = metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer "+fixtureGateway, "x-openlet-user-id", transportActor))
	response, err := client.GetDownload(ctx, &letfsv1.GetDownloadRequest{FilesystemId: "drive", NodeId: "node"})
	require.NoError(t, err)
	require.Equal(t, transportBytes, response.Download.GetInlineContent())
	cancelable, cancel := context.WithCancel(ctx)
	defer cancel()
	result := make(chan error, 1)
	go func() {
		_, err := client.GetDownload(cancelable, &letfsv1.GetDownloadRequest{FilesystemId: "drive", NodeId: "slow"})
		result <- err
	}()
	select {
	case <-f.slowStarted:
	case <-ctx.Done():
		t.Fatal("native handler did not start")
	}
	cancel()
	require.Equal(t, codes.Canceled, status.Code(<-result))
	select {
	case <-f.slowStopped:
	case <-ctx.Done():
		t.Fatal("native cancellation did not reach handler")
	}
}

func TestIntegrationNativeArchiveFramesBackpressureAndAuthority(t *testing.T) {
	s, fixture := transportServer(t, "127.0.0.1:0")
	connection, err := grpc.NewClient(strings.TrimPrefix(s.URL, "http://"), grpc.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	client := letfsv1.NewFilesystemServiceClient(connection)
	ctx, stop := context.WithTimeout(t.Context(), 5*time.Second)
	defer stop()
	verified := metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer "+fixtureGateway, "x-openlet-user-id", transportActor))
	stream, err := client.StreamArchive(verified, &letfsv1.StreamArchiveRequest{FilesystemId: "drive", NodeId: "node"})
	require.NoError(t, err)
	frame, err := stream.Recv()
	require.NoError(t, err)
	require.Equal(t, "report.zip", frame.GetMetadata().Filename)
	var data []byte
	for {
		frame, err = stream.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		require.NoError(t, err)
		require.Nil(t, frame.GetMetadata())
		require.LessOrEqual(t, len(frame.GetData()), 65536)
		data = append(data, frame.GetData()...)
	}
	archive, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	require.NoError(t, err)
	require.Len(t, archive.File, 1)
	content, err := archive.File[0].Open()
	require.NoError(t, err)
	body, err := io.ReadAll(content)
	require.NoError(t, err)
	require.NoError(t, content.Close())
	require.Equal(t, transportBytes, body)

	stream, err = client.StreamArchive(ctx, &letfsv1.StreamArchiveRequest{FilesystemId: "drive"})
	require.NoError(t, err)
	_, err = stream.Recv()
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	_, err = letfsv1.NewIngestServiceClient(connection).PrepareParse(verified, &letfsv1.PrepareParseRequest{})
	require.Equal(t, codes.PermissionDenied, status.Code(err), "gateway cannot invoke ingest authority")

	stream, err = client.StreamArchive(verified, &letfsv1.StreamArchiveRequest{FilesystemId: "drive", NodeId: "failure"})
	require.NoError(t, err)
	_, err = stream.Recv()
	require.NoError(t, err)
	_, err = stream.Recv()
	require.Equal(t, codes.Internal, status.Code(err))
	require.NotContains(t, err.Error(), "secret", "stream trailers use the same error sanitization")

	cancelable, cancel := context.WithCancel(verified)
	defer cancel()
	_, err = client.StreamArchive(cancelable, &letfsv1.StreamArchiveRequest{FilesystemId: "drive", NodeId: "slow"})
	require.NoError(t, err)
	select {
	case <-fixture.streamStarted:
	case <-ctx.Done():
		t.Fatal("stream did not start")
	}
	select {
	case <-fixture.streamStopped:
		t.Fatal("producer completed without its consumer: backpressure is missing")
	case <-time.After(100 * time.Millisecond):
	}
	cancel()
	select {
	case <-fixture.streamStopped:
	case <-ctx.Done():
		t.Fatal("canceled slow stream retained its producer")
	}
}
