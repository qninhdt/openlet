package sdk

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net"
	"sync"
	"testing"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"go.opentelemetry.io/otel"
	collectormetric "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	collector "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
)

type receiver struct {
	collector.UnimplementedTraceServiceServer
	mu       sync.Mutex
	requests []*collector.ExportTraceServiceRequest
}

func (r *receiver) Export(_ context.Context, req *collector.ExportTraceServiceRequest) (*collector.ExportTraceServiceResponse, error) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.requests = append(r.requests, req)
	return &collector.ExportTraceServiceResponse{}, nil
}

type metricReceiver struct {
	collectormetric.UnimplementedMetricsServiceServer
}

func (*metricReceiver) Export(context.Context, *collectormetric.ExportMetricsServiceRequest) (*collectormetric.ExportMetricsServiceResponse, error) {
	return &collectormetric.ExportMetricsServiceResponse{}, nil
}

func TestTelemetryExportAndCorrelation(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	oldLogger, oldTracer, oldMeter, oldErrors := slog.Default(), otel.GetTracerProvider(), otel.GetMeterProvider(), otel.GetErrorHandler()
	defer func() {
		slog.SetDefault(oldLogger)
		otel.SetTracerProvider(oldTracer)
		otel.SetMeterProvider(oldMeter)
		otel.SetErrorHandler(oldErrors)
	}()
	var logs bytes.Buffer
	slog.SetDefault(slog.New(slog.NewJSONHandler(&logs, nil)))
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	exporter := grpc.NewServer()
	defer exporter.Stop()
	received := &receiver{}
	collector.RegisterTraceServiceServer(exporter, received)
	collectormetric.RegisterMetricsServiceServer(exporter, &metricReceiver{})
	go exporter.Serve(listener)
	shutdown, err := InitTelemetry(ctx, "test-service", "test", Telemetry{OTLPEndpoint: "http://" + listener.Addr().String(), TraceSampleRatio: 1, MetricsExportIntervalSeconds: 60})
	if err != nil {
		t.Fatal(err)
	}
	defer shutdown(context.Background())
	rpcListener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server := grpc.NewServer(grpc.StatsHandler(otelgrpc.NewServerHandler()), grpc.UnaryInterceptor(func(ctx context.Context, req any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
		slog.Default().With("operation", "check").InfoContext(ctx, "request")
		return handler(ctx, req)
	}))
	defer server.Stop()
	healthpb.RegisterHealthServer(server, health.NewServer())
	go server.Serve(rpcListener)
	connection, err := Dial(rpcListener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer connection.Close()
	parent, span := otel.Tracer("test").Start(ctx, "root")
	_, err = healthpb.NewHealthClient(connection).Check(parent, &healthpb.HealthCheckRequest{})
	if err != nil {
		t.Fatal(err)
	}
	span.End()
	if err = shutdown(ctx); err != nil {
		t.Fatal(err)
	}
	var record map[string]any
	if err = json.Unmarshal(logs.Bytes(), &record); err != nil {
		t.Fatal(err)
	}
	if record["trace_id"] != span.SpanContext().TraceID().String() || record["span_id"] == "" || record["service.name"] != "test-service" || record["service.instance.id"] == "" || record["service.version"] == "" {
		t.Fatalf("missing correlation/identity: %v", record)
	}
	received.mu.Lock()
	defer received.mu.Unlock()
	traceID := span.SpanContext().TraceID()
	count := 0
	ids := map[string]bool{}
	for _, req := range received.requests {
		for _, res := range req.ResourceSpans {
			for _, scope := range res.ScopeSpans {
				for _, exported := range scope.Spans {
					if !bytes.Equal(exported.TraceId, traceID[:]) {
						t.Fatal("gRPC lost trace context")
					}
					ids[string(exported.SpanId)] = true
					count++
				}
			}
		}
	}
	if count != 3 {
		t.Fatalf("want root + gRPC client/server, got %d", count)
	}
	for _, req := range received.requests {
		for _, res := range req.ResourceSpans {
			for _, scope := range res.ScopeSpans {
				for _, exported := range scope.Spans {
					if len(exported.ParentSpanId) > 0 && !ids[string(exported.ParentSpanId)] {
						t.Fatal("missing parent span")
					}
				}
			}
		}
	}
}

func TestTelemetryDisabledAndUnavailable(t *testing.T) {
	oldLogger, oldTracer, oldMeter, oldErrors := slog.Default(), otel.GetTracerProvider(), otel.GetMeterProvider(), otel.GetErrorHandler()
	defer func() {
		slog.SetDefault(oldLogger)
		otel.SetTracerProvider(oldTracer)
		otel.SetMeterProvider(oldMeter)
		otel.SetErrorHandler(oldErrors)
	}()
	disabled, err := InitTelemetry(context.Background(), "disabled", "test", Telemetry{})
	if err != nil {
		t.Fatal(err)
	}
	if err = disabled(context.Background()); err != nil {
		t.Fatal(err)
	}
	shutdown, err := InitTelemetry(context.Background(), "unavailable", "test", Telemetry{OTLPEndpoint: "http://127.0.0.1:1", TraceSampleRatio: 1, MetricsExportIntervalSeconds: 60})
	if err != nil {
		t.Fatal(err)
	}
	_, span := otel.Tracer("test").Start(context.Background(), "request")
	span.End()
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	started := time.Now()
	_ = shutdown(ctx)
	if time.Since(started) > time.Second {
		t.Fatal("shutdown exceeded deadline")
	}
}
