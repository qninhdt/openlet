package rpc

import (
	"context"
	"crypto/tls"
	"errors"
	"net"
	"strconv"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"go.opentelemetry.io/otel/propagation"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/metadata"
)

const (
	MaxMessageBytes = 8 << 20
	UnaryTimeout    = 2 * time.Minute
	StreamTimeout   = 30 * time.Minute
)

// Transport permits plaintext only in an explicitly trusted local deployment/test.
type Transport struct {
	TLS            *tls.Config
	AllowPlaintext bool
}

func (t Transport) credentials() (credentials.TransportCredentials, error) {
	if t.AllowPlaintext {
		if t.TLS != nil {
			return nil, errors.New("RPC TLS and plaintext configuration conflict")
		}
		return insecure.NewCredentials(), nil
	}
	configuration := &tls.Config{MinVersion: tls.VersionTLS12}
	if t.TLS != nil {
		configuration = t.TLS.Clone()
		if configuration.InsecureSkipVerify || (configuration.MinVersion != 0 && configuration.MinVersion < tls.VersionTLS12) {
			return nil, errors.New("RPC TLS must verify peers and require TLS 1.2 or later")
		}
		if configuration.MinVersion == 0 {
			configuration.MinVersion = tls.VersionTLS12
		}
	}
	return credentials.NewTLS(configuration), nil
}

type bearerCredential struct {
	token  string
	secure bool
}

func (c bearerCredential) GetRequestMetadata(context.Context, ...string) (map[string]string, error) {
	return map[string]string{"authorization": "Bearer " + c.token}, nil
}

func (c bearerCredential) RequireTransportSecurity() bool { return c.secure }

// Dial returns a caller-owned connection; readiness is established by a real health/RPC call.
// Application failures are not automatically retried after an ambiguous result.
func Dial(address, token string, transport Transport) (*grpc.ClientConn, error) {
	host, port, err := net.SplitHostPort(address)
	portNumber, portErr := strconv.Atoi(port)
	if err != nil || host == "" || portErr != nil || portNumber < 1 || portNumber > 65535 || !validServiceToken(token) {
		return nil, errors.New("invalid RPC client configuration")
	}
	credential, err := transport.credentials()
	if err != nil {
		return nil, err
	}
	return grpc.NewClient(address,
		grpc.WithTransportCredentials(credential),
		grpc.WithPerRPCCredentials(bearerCredential{token, !transport.AllowPlaintext}),
		grpc.WithDisableRetry(),
		grpc.WithMaxHeaderListSize(16<<10),
		grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(MaxMessageBytes), grpc.MaxCallSendMsgSize(MaxMessageBytes)),
		grpc.WithUnaryInterceptor(unaryClientDeadline),
		grpc.WithStreamInterceptor(streamClientDeadline),
		grpc.WithStatsHandler(otelgrpc.NewClientHandler(otelgrpc.WithPropagators(propagation.TraceContext{}))),
	)
}

// NewServer requires application authentication; only the standard readiness Check is public.
// The owner registers health and updates its status from actual dependency readiness.
func NewServer(authentication *Authenticator, transport Transport) (*grpc.Server, error) {
	if authentication == nil {
		return nil, errors.New("missing RPC authenticator")
	}
	if !transport.AllowPlaintext && (transport.TLS == nil || (len(transport.TLS.Certificates) == 0 && transport.TLS.GetCertificate == nil && transport.TLS.GetConfigForClient == nil)) {
		return nil, errors.New("missing RPC server TLS certificate")
	}
	credential, err := transport.credentials()
	if err != nil {
		return nil, err
	}
	authenticate := authentication.Unary()
	return grpc.NewServer(
		grpc.Creds(credential),
		grpc.MaxRecvMsgSize(MaxMessageBytes), grpc.MaxSendMsgSize(MaxMessageBytes),
		grpc.MaxHeaderListSize(16<<10),
		grpc.StatsHandler(otelgrpc.NewServerHandler(otelgrpc.WithPropagators(propagation.TraceContext{}))),
		grpc.UnaryInterceptor(func(ctx context.Context, request any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
			ctx, cancel := context.WithTimeout(ctx, UnaryTimeout)
			defer cancel()
			var response any
			var err error
			if info.FullMethod == healthv1.Health_Check_FullMethodName {
				response, err = handler(ctx, request)
			} else {
				response, err = authenticate(ctx, request, info, handler)
			}
			return response, NormalizeError(err)
		}),
		grpc.ChainStreamInterceptor(func(server any, stream grpc.ServerStream, info *grpc.StreamServerInfo, handler grpc.StreamHandler) error {
			ctx, cancel := context.WithTimeout(stream.Context(), StreamTimeout)
			defer cancel()
			return NormalizeError(handler(server, &authenticatedStream{ServerStream: stream, ctx: ctx}))
		}, authentication.Stream()),
	), nil
}

func unaryClientDeadline(ctx context.Context, method string, request, response any, connection *grpc.ClientConn, invoke grpc.UnaryInvoker, options ...grpc.CallOption) error {
	ctx, cancel := context.WithTimeout(ctx, UnaryTimeout)
	defer cancel()
	return invoke(ctx, method, request, response, connection, options...)
}

type boundedClientStream struct {
	grpc.ClientStream
	cancel context.CancelFunc
}

func (s *boundedClientStream) Header() (metadata.MD, error) {
	header, err := s.ClientStream.Header()
	if err != nil {
		s.cancel()
	}
	return header, err
}

func (s *boundedClientStream) CloseSend() error {
	err := s.ClientStream.CloseSend()
	if err != nil {
		s.cancel()
	}
	return err
}

func (s *boundedClientStream) RecvMsg(message any) error {
	err := s.ClientStream.RecvMsg(message)
	if err != nil {
		s.cancel()
	}
	return err
}

func (s *boundedClientStream) SendMsg(message any) error {
	err := s.ClientStream.SendMsg(message)
	if err != nil {
		s.cancel()
	}
	return err
}

func streamClientDeadline(ctx context.Context, descriptor *grpc.StreamDesc, connection *grpc.ClientConn, method string, stream grpc.Streamer, options ...grpc.CallOption) (grpc.ClientStream, error) {
	ctx, cancel := context.WithTimeout(ctx, StreamTimeout)
	result, err := stream(ctx, descriptor, connection, method, options...)
	if err != nil {
		cancel()
		return nil, err
	}
	return &boundedClientStream{ClientStream: result, cancel: cancel}, nil
}
