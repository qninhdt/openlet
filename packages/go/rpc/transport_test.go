package rpc

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/baggage"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/health"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/identity"
)

const testTransportToken = "isolated-bounded-rpc-service-token-12345"

type callObservation struct {
	principal identity.Principal
	remaining time.Duration
	span      trace.SpanContext
	baggage   int
}

type boundedFixture struct {
	letfsv1.UnimplementedFilesystemServiceServer
	observed chan callObservation
	stopped  chan struct{}
	calls    atomic.Int32
}

func (f *boundedFixture) observe(ctx context.Context) {
	principal, _ := identity.FromContext(ctx)
	deadline, _ := ctx.Deadline()
	f.observed <- callObservation{principal, time.Until(deadline), trace.SpanContextFromContext(ctx), baggage.FromContext(ctx).Len()}
}

func (f *boundedFixture) GetNode(ctx context.Context, request *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error) {
	f.calls.Add(1)
	f.observe(ctx)
	switch request.NodeId {
	case "wait":
		<-ctx.Done()
		close(f.stopped)
		return nil, ctx.Err()
	case "unavailable":
		return nil, status.Error(codes.Unavailable, "private dependency diagnostic")
	case "large":
		return &letfsv1.GetNodeResponse{Node: &letfsv1.Node{Name: strings.Repeat("x", MaxMessageBytes+1)}}, nil
	default:
		return &letfsv1.GetNodeResponse{Node: &letfsv1.Node{Id: request.NodeId}}, nil
	}
}

func (f *boundedFixture) StreamArchive(_ *letfsv1.StreamArchiveRequest, stream grpc.ServerStreamingServer[letfsv1.StreamArchiveResponse]) error {
	defer close(f.stopped)
	f.observe(stream.Context())
	if err := stream.Send(&letfsv1.StreamArchiveResponse{Frame: &letfsv1.StreamArchiveResponse_Metadata{Metadata: &letfsv1.ArchiveMetadata{Filename: "archive.zip"}}}); err != nil {
		return err
	}
	<-stream.Context().Done()
	return stream.Context().Err()
}

func startBoundedRPC(t *testing.T, transport Transport) (string, *boundedFixture, *health.Server) {
	t.Helper()
	authentication, err := NewAuthenticator([]Credential{{Service: "workspace", Token: testTransportToken,
		Methods: []string{letfsv1.FilesystemService_GetNode_FullMethodName, letfsv1.FilesystemService_StreamArchive_FullMethodName}}})
	require.NoError(t, err)
	server, err := NewServer(authentication, transport)
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	fixture := &boundedFixture{observed: make(chan callObservation, 16), stopped: make(chan struct{})}
	letfsv1.RegisterFilesystemServiceServer(server, fixture)
	readiness := health.NewServer()
	readiness.SetServingStatus("", healthv1.HealthCheckResponse_NOT_SERVING)
	healthv1.RegisterHealthServer(server, readiness)
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() {
		server.Stop()
		require.NoError(t, <-done)
	})
	return listener.Addr().String(), fixture, readiness
}

func connectBoundedRPC(t *testing.T, address, token string, transport Transport) *grpc.ClientConn {
	t.Helper()
	connection, err := Dial(address, token, transport)
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	return connection
}

func TestBoundedRPCAdmissionTracingHealthAndSize(t *testing.T) {
	provider := sdktrace.NewTracerProvider(sdktrace.WithSampler(sdktrace.AlwaysSample()))
	previous := otel.GetTracerProvider()
	otel.SetTracerProvider(provider)
	t.Cleanup(func() {
		otel.SetTracerProvider(previous)
		require.NoError(t, provider.Shutdown(context.Background()))
	})
	transport := Transport{AllowPlaintext: true}
	address, fixture, readiness := startBoundedRPC(t, transport)
	connection := connectBoundedRPC(t, address, testTransportToken, transport)
	client := letfsv1.NewFilesystemServiceClient(connection)
	member, err := baggage.NewMember("private", "do-not-propagate")
	require.NoError(t, err)
	values, err := baggage.New(member)
	require.NoError(t, err)
	ctx, parent := provider.Tracer("test").Start(baggage.ContextWithBaggage(t.Context(), values), "caller")
	defer parent.End()
	response, err := client.GetNode(ctx, &letfsv1.GetNodeRequest{NodeId: "node"})
	require.NoError(t, err)
	require.Equal(t, "node", response.Node.Id)
	observation := <-fixture.observed
	require.Equal(t, "workspace", observation.principal.Service)
	require.Equal(t, parent.SpanContext().TraceID(), observation.span.TraceID())
	require.NotEqual(t, parent.SpanContext().SpanID(), observation.span.SpanID())
	require.Zero(t, observation.baggage)
	require.Positive(t, observation.remaining)
	require.LessOrEqual(t, observation.remaining, UnaryTimeout)

	healthClient := healthv1.NewHealthClient(connection)
	state, err := healthClient.Check(t.Context(), &healthv1.HealthCheckRequest{})
	require.NoError(t, err)
	require.Equal(t, healthv1.HealthCheckResponse_NOT_SERVING, state.Status)
	readiness.SetServingStatus("", healthv1.HealthCheckResponse_SERVING)
	state, err = healthClient.Check(t.Context(), &healthv1.HealthCheckRequest{})
	require.NoError(t, err)
	require.Equal(t, healthv1.HealthCheckResponse_SERVING, state.Status)

	_, err = client.GetNode(t.Context(), &letfsv1.GetNodeRequest{NodeId: "unavailable"})
	require.Equal(t, codes.Unavailable, status.Code(err))
	require.NotContains(t, err.Error(), "private dependency")
	require.Equal(t, int32(2), fixture.calls.Load(), "ambiguous application failures cannot be retried")
	_, err = client.GetNode(t.Context(), &letfsv1.GetNodeRequest{NodeId: strings.Repeat("x", MaxMessageBytes+1)})
	require.Equal(t, codes.ResourceExhausted, status.Code(err))
	require.Equal(t, int32(2), fixture.calls.Load(), "oversized requests never reach the application")
	_, err = client.GetNode(t.Context(), &letfsv1.GetNodeRequest{NodeId: strings.Repeat("x", MaxMessageBytes+1)}, grpc.MaxCallSendMsgSize(2*MaxMessageBytes))
	require.Equal(t, codes.ResourceExhausted, status.Code(err))
	require.Equal(t, int32(2), fixture.calls.Load(), "server independently enforces the message limit")
	_, err = client.GetNode(t.Context(), &letfsv1.GetNodeRequest{NodeId: "large"})
	require.Equal(t, codes.ResourceExhausted, status.Code(err))
	wrong := connectBoundedRPC(t, address, strings.Repeat("w", 32), transport)
	_, err = letfsv1.NewFilesystemServiceClient(wrong).GetNode(t.Context(), &letfsv1.GetNodeRequest{})
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	require.Equal(t, int32(3), fixture.calls.Load())
}

func TestBoundedRPCCancellation(t *testing.T) {
	for _, streaming := range []bool{false, true} {
		t.Run(map[bool]string{false: "unary", true: "stream"}[streaming], func(t *testing.T) {
			transport := Transport{AllowPlaintext: true}
			address, fixture, _ := startBoundedRPC(t, transport)
			client := letfsv1.NewFilesystemServiceClient(connectBoundedRPC(t, address, testTransportToken, transport))
			ctx, cancel := context.WithCancel(t.Context())
			defer cancel()
			result := make(chan error, 1)
			go func() {
				if streaming {
					stream, err := client.StreamArchive(ctx, &letfsv1.StreamArchiveRequest{})
					if err == nil {
						_, err = stream.Recv()
					}
					if err == nil {
						_, err = stream.Recv()
					}
					result <- err
				} else {
					_, err := client.GetNode(ctx, &letfsv1.GetNodeRequest{NodeId: "wait"})
					result <- err
				}
			}()
			select {
			case observation := <-fixture.observed:
				limit := UnaryTimeout
				if streaming {
					limit = StreamTimeout
				}
				require.Positive(t, observation.remaining)
				require.Greater(t, observation.remaining, limit/2)
				require.LessOrEqual(t, observation.remaining, limit)
			case <-time.After(5 * time.Second):
				t.Fatal("RPC never reached the application")
			}
			cancel()
			select {
			case err := <-result:
				require.Equal(t, codes.Canceled, status.Code(err))
			case <-time.After(5 * time.Second):
				t.Fatal("caller cancellation did not return")
			}
			select {
			case <-fixture.stopped:
			case <-time.After(5 * time.Second):
				t.Fatal("caller cancellation did not stop the application")
			}
		})
	}
}

func TestBoundedRPCPreservesEarlierDeadline(t *testing.T) {
	transport := Transport{AllowPlaintext: true}
	address, fixture, _ := startBoundedRPC(t, transport)
	client := letfsv1.NewFilesystemServiceClient(connectBoundedRPC(t, address, testTransportToken, transport))
	ctx, cancel := context.WithTimeout(t.Context(), 250*time.Millisecond)
	defer cancel()
	_, err := client.GetNode(ctx, &letfsv1.GetNodeRequest{NodeId: "wait"})
	require.Equal(t, codes.DeadlineExceeded, status.Code(err))
	select {
	case observation := <-fixture.observed:
		require.LessOrEqual(t, observation.remaining, 250*time.Millisecond)
	case <-time.After(time.Second):
		t.Fatal("deadline test never reached the application")
	}
	select {
	case <-fixture.stopped:
	case <-time.After(time.Second):
		t.Fatal("deadline did not stop the application")
	}
}

func TestRPCTLSVerification(t *testing.T) {
	https := httptest.NewTLSServer(http.NotFoundHandler())
	certificate, config := https.Certificate(), https.TLS.Clone()
	https.Close()
	address, _, _ := startBoundedRPC(t, Transport{TLS: config})
	roots := x509.NewCertPool()
	roots.AddCert(certificate)
	trusted := Transport{TLS: &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12}}
	client := letfsv1.NewFilesystemServiceClient(connectBoundedRPC(t, address, testTransportToken, trusted))
	_, err := client.GetNode(t.Context(), &letfsv1.GetNodeRequest{})
	require.NoError(t, err)
	for _, transport := range []Transport{{}, {TLS: &tls.Config{RootCAs: roots, ServerName: "untrusted.example.test"}}} {
		client := letfsv1.NewFilesystemServiceClient(connectBoundedRPC(t, address, testTransportToken, transport))
		ctx, cancel := context.WithTimeout(t.Context(), time.Second)
		_, err := client.GetNode(ctx, &letfsv1.GetNodeRequest{})
		cancel()
		require.Equal(t, codes.Unavailable, status.Code(err), "untrusted certificates or hostnames cannot authenticate")
	}
}

func TestRPCRejectsUnsafeTransportConfiguration(t *testing.T) {
	for _, token := range []string{"short", testTransportToken + "\n", testTransportToken + "\x00", testTransportToken + " "} {
		_, err := Dial("localhost:50051", token, Transport{})
		require.Error(t, err)
		_, err = NewAuthenticator([]Credential{{Service: "workspace", Token: token, Methods: []string{letfsv1.FilesystemService_GetNode_FullMethodName}}})
		require.Error(t, err)
	}
	for _, transport := range []Transport{
		{TLS: &tls.Config{InsecureSkipVerify: true}},
		{TLS: &tls.Config{MinVersion: tls.VersionTLS10}},
		{TLS: &tls.Config{}, AllowPlaintext: true},
	} {
		_, err := Dial("localhost:50051", testTransportToken, transport)
		require.Error(t, err)
	}
	for _, address := range []string{"", "example.test", "localhost:0", "localhost:65536", ":50051"} {
		_, err := Dial(address, testTransportToken, Transport{})
		require.Error(t, err)
	}
	_, err := NewServer(nil, Transport{AllowPlaintext: true})
	require.Error(t, err)
	authentication, err := NewAuthenticator([]Credential{{Service: "workspace", Token: testTransportToken, Methods: []string{letfsv1.FilesystemService_GetNode_FullMethodName}}})
	require.NoError(t, err)
	_, err = NewServer(authentication, Transport{})
	require.Error(t, err, "TLS server startup needs a certificate")
}
