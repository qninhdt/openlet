package http

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	"go.opentelemetry.io/otel/trace"
)

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
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		parent := trace.SpanContextFromContext(propagation.TraceContext{}.Extract(r.Context(), propagation.HeaderCarrier(r.Header)))
		if parent.TraceID().String() != traceID || r.Header.Get("Baggage") != "" {
			t.Error("outbound request lost W3C context or forwarded private baggage")
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"email_addresses":[]}`))
	}))
	defer upstream.Close()
	s := Server{}
	s.Config.GatewayToken = strings.Repeat("x", 43)
	s.Clerk.BaseURL = upstream.URL
	router := s.Router()
	router.GET("/v1/probe/:id", func(c *gin.Context) {
		if _, err := s.Clerk.VerifiedEmails(c.Request.Context(), "user_trace"); err != nil {
			t.Error(err)
			c.Status(503)
			return
		}
		c.Status(204)
	})
	request := httptest.NewRequest(http.MethodGet, "/v1/probe/"+uuid.NewString()+"?token=must-not-export", nil)
	request.Header.Set("X-Gateway-Token", s.Config.GatewayToken)
	request.Header.Set("X-Clerk-Sub", "user_trace")
	request.Header.Set("X-Openlet-User-ID", uuid.NewString())
	request.Header.Set("Traceparent", "00-"+traceID+"-1234567890abcdef-01")
	request.Header.Set("Baggage", "private=must-not-export")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != 204 {
		t.Fatalf("request failed: %d", response.Code)
	}
	spans := exporter.GetSpans()
	if len(spans) != 2 {
		t.Fatalf("want inbound and outbound spans, got %d", len(spans))
	}
	var inbound, outbound tracetest.SpanStub
	for _, span := range spans {
		if span.SpanKind == trace.SpanKindServer {
			inbound = span
			if span.Name != "GET /v1/probe/:id" {
				t.Fatalf("raw path span name: %s", span.Name)
			}
		} else if span.SpanKind == trace.SpanKindClient {
			outbound = span
		}
		for _, attribute := range span.Attributes {
			if strings.Contains(attribute.Value.Emit(), "must-not-export") || strings.Contains(attribute.Value.Emit(), s.Config.GatewayToken) {
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
}
