package http

import (
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	accountclient "github.com/qninhdt/openlet/packages/go/clients/account"
	accountv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/account/v1"
	sharedrpc "github.com/qninhdt/openlet/packages/go/rpc"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	"go.opentelemetry.io/otel/trace"
	"google.golang.org/grpc/metadata"
)

type tracedAccount struct {
	accountv1.UnimplementedAccountServiceServer
	t *testing.T
}

func (s tracedAccount) GetVerifiedEmails(ctx context.Context, _ *accountv1.GetVerifiedEmailsRequest) (*accountv1.GetVerifiedEmailsResponse, error) {
	parent := trace.SpanContextFromContext(ctx)
	md, _ := metadata.FromIncomingContext(ctx)
	if parent.TraceID().String() != "1234567890abcdef1234567890abcdef" || len(md.Get("baggage")) != 0 {
		s.t.Error("outbound request lost W3C context or forwarded private baggage")
	}
	return &accountv1.GetVerifiedEmailsResponse{}, nil
}

func TestGinPropagatesHTTPTraceWithoutBaggage(t *testing.T) {
	exporter := tracetest.NewInMemoryExporter()
	provider := sdktrace.NewTracerProvider(sdktrace.WithSyncer(exporter))
	previousProvider, previousPropagator := otel.GetTracerProvider(), otel.GetTextMapPropagator()
	otel.SetTracerProvider(provider)
	otel.SetTextMapPropagator(propagation.TraceContext{})
	t.Cleanup(func() {
		otel.SetTracerProvider(previousProvider)
		otel.SetTextMapPropagator(previousPropagator)
		_ = provider.Shutdown(t.Context())
	})
	const traceID = "1234567890abcdef1234567890abcdef"
	token := strings.Repeat("w", 32)
	authentication, err := sharedrpc.NewAuthenticator([]sharedrpc.Credential{{Service: "workspace", Token: token, Methods: []string{accountv1.AccountService_GetVerifiedEmails_FullMethodName}}})
	if err != nil {
		t.Fatal(err)
	}
	upstream, err := sharedrpc.NewServer(authentication, sharedrpc.Transport{AllowPlaintext: true})
	if err != nil {
		t.Fatal(err)
	}
	accountv1.RegisterAccountServiceServer(upstream, tracedAccount{t: t})
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	stopped := make(chan error, 1)
	go func() { stopped <- upstream.Serve(listener) }()
	t.Cleanup(func() {
		upstream.Stop()
		if err := <-stopped; err != nil {
			t.Error(err)
		}
	})
	connection, err := sharedrpc.Dial(listener.Addr().String(), token, sharedrpc.Transport{AllowPlaintext: true})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = connection.Close() })
	s := Server{}
	s.Config.GatewayToken = strings.Repeat("x", 43)
	accountClient := accountclient.Client{API: accountv1.NewAccountServiceClient(connection)}
	router := s.Router()
	router.GET("/v1/probe/:id", func(c *gin.Context) {
		if _, err := accountClient.VerifiedEmails(c.Request.Context(), uuid.New()); err != nil {
			t.Error(err)
			c.Status(503)
			return
		}
		c.Status(204)
	})
	request := httptest.NewRequest(http.MethodGet, "/v1/probe/"+uuid.NewString()+"?token=must-not-export", nil)
	request.Header.Set("X-Gateway-Token", s.Config.GatewayToken)
	request.Header.Set("X-Clerk-Sub", "user_trace")
	request.Header.Set("X-Openlet-Account-ID", uuid.NewString())
	request.Header.Set("Traceparent", "00-"+traceID+"-1234567890abcdef-01")
	request.Header.Set("Baggage", "private=must-not-export")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != 204 {
		t.Fatalf("request failed: %d", response.Code)
	}
	spans := exporter.GetSpans()
	if len(spans) != 3 {
		t.Fatalf("want HTTP inbound and gRPC client/server spans, got %d", len(spans))
	}
	var inbound, outbound, account tracetest.SpanStub
	for _, span := range spans {
		if span.SpanKind == trace.SpanKindServer && span.Name == "GET /v1/probe/:id" {
			inbound = span
		} else if span.SpanKind == trace.SpanKindServer {
			account = span
		} else if span.SpanKind == trace.SpanKindClient {
			outbound = span
		}
		for _, attribute := range span.Attributes {
			if strings.Contains(attribute.Value.String(), "must-not-export") || strings.Contains(attribute.Value.String(), s.Config.GatewayToken) {
				t.Fatalf("sensitive telemetry attribute: %s", attribute.Key)
			}
		}
		if span.SpanContext.TraceID().String() != traceID {
			t.Fatal("HTTP span started another trace")
		}
	}
	if outbound.Parent.SpanID() != inbound.SpanContext.SpanID() {
		t.Fatal("outbound span is not a child of inbound HTTP")
	}
	if account.Parent.SpanID() != outbound.SpanContext.SpanID() {
		t.Fatal("Account span is not a child of outbound RPC")
	}
}
