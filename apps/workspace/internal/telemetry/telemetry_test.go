package telemetry

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"go.opentelemetry.io/otel"
	collector "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	"google.golang.org/protobuf/proto"
)

func TestOTLPResourceAndCorrelatedLogs(t *testing.T) {
	exported := make(chan *collector.ExportTraceServiceRequest, 1)
	receiver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		var request collector.ExportTraceServiceRequest
		if err != nil || proto.Unmarshal(body, &request) != nil || r.URL.Path != "/v1/traces" {
			t.Error("invalid native OTLP request")
			w.WriteHeader(400)
			return
		}
		exported <- &request
		w.Header().Set("Content-Type", "application/x-protobuf")
	}))
	defer receiver.Close()
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", receiver.URL)
	t.Setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "")
	t.Setenv("OTEL_RESOURCE_ATTRIBUTES", "deployment.environment.name=test")
	t.Setenv("OTEL_SERVICE_NAME", "")
	t.Setenv("OTEL_SDK_DISABLED", "false")
	t.Setenv("OTEL_TRACES_EXPORTER", "otlp")
	t.Setenv("OTEL_METRICS_EXPORTER", "none")
	t.Setenv("OTEL_TRACES_SAMPLER", "parentbased_traceidratio")
	t.Setenv("OTEL_TRACES_SAMPLER_ARG", "1")
	oldTrace, oldMetric, oldPropagation, oldLogger := otel.GetTracerProvider(), otel.GetMeterProvider(), otel.GetTextMapPropagator(), slog.Default()
	t.Cleanup(func() {
		otel.SetTracerProvider(oldTrace)
		otel.SetMeterProvider(oldMetric)
		otel.SetTextMapPropagator(oldPropagation)
		slog.SetDefault(oldLogger)
	})
	stop, err := Init(t.Context(), "openlet-workspace")
	if err != nil {
		t.Fatal(err)
	}
	ctx, span := otel.Tracer("test").Start(t.Context(), "operation")
	var output bytes.Buffer
	logger := slog.New(logHandler{slog.NewJSONHandler(&output, nil)}).With("component", "native-test")
	logger.InfoContext(ctx, "completed")
	span.End()
	if !strings.Contains(output.String(), span.SpanContext().TraceID().String()) || !strings.Contains(output.String(), span.SpanContext().SpanID().String()) {
		t.Fatal("active-span log does not correlate")
	}
	deadline, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := stop(deadline); err != nil {
		t.Fatal(err)
	}
	select {
	case request := <-exported:
		if len(request.ResourceSpans) != 1 {
			t.Fatal("missing exported resource")
		}
		attributes := map[string]string{}
		for _, item := range request.ResourceSpans[0].Resource.Attributes {
			attributes[item.Key] = item.Value.GetStringValue()
		}
		if attributes["service.name"] != "openlet-workspace" || attributes["service.version"] == "" || attributes["deployment.environment.name"] != "test" {
			t.Fatalf("incorrect resource attributes: %v", attributes)
		}
		if len(request.ResourceSpans[0].ScopeSpans[0].Spans) != 1 {
			t.Fatal("missing exported span")
		}
	default:
		t.Fatal("configured exporter did not send a trace")
	}
}

func TestNoEndpointAndUnavailableExporterShutdown(t *testing.T) {
	for _, endpoint := range []string{"", "http://127.0.0.1:1"} {
		t.Run(endpoint, func(t *testing.T) {
			t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
			t.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
			t.Setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "")
			t.Setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
			t.Setenv("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "")
			t.Setenv("OTEL_TRACES_SAMPLER", "always_on")
			t.Setenv("OTEL_TRACES_EXPORTER", "otlp")
			t.Setenv("OTEL_METRICS_EXPORTER", "none")
			t.Setenv("OTEL_SDK_DISABLED", "false")
			oldTrace, oldMetric, oldPropagation, oldLogger := otel.GetTracerProvider(), otel.GetMeterProvider(), otel.GetTextMapPropagator(), slog.Default()
			t.Cleanup(func() {
				otel.SetTracerProvider(oldTrace)
				otel.SetMeterProvider(oldMetric)
				otel.SetTextMapPropagator(oldPropagation)
				slog.SetDefault(oldLogger)
			})
			stop, err := Init(t.Context(), "openlet-workspace")
			if err != nil {
				t.Fatal(err)
			}
			_, span := otel.Tracer("test").Start(t.Context(), "operation")
			span.End()
			deadline, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
			defer cancel()
			started := time.Now()
			err = stop(deadline)
			if endpoint == "" && err != nil {
				t.Fatalf("no endpoint attempted an export: %v", err)
			}
			if time.Since(started) > time.Second {
				t.Fatal("exporter blocked shutdown")
			}
		})
	}
}
