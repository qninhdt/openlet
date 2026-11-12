package sdk

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"net/url"
	"runtime/debug"
	"time"

	"github.com/google/uuid"
	otelruntime "go.opentelemetry.io/contrib/instrumentation/runtime"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	"go.opentelemetry.io/otel/sdk/trace"
	traceapi "go.opentelemetry.io/otel/trace"
)

type Telemetry struct {
	OTLPEndpoint                 string  `yaml:"otlp_endpoint"`
	TraceSampleRatio             float64 `yaml:"trace_sample_ratio"`
	MetricsExportIntervalSeconds int     `yaml:"metrics_export_interval_seconds"`
}

func InitTelemetry(ctx context.Context, name, environment string, c Telemetry) (func(context.Context) error, error) {
	otel.SetTextMapPropagator(propagation.TraceContext{})
	version := "dev"
	if build, ok := debug.ReadBuildInfo(); ok {
		if build.Main.Version != "" && build.Main.Version != "(devel)" {
			version = build.Main.Version
		}
		for _, setting := range build.Settings {
			if setting.Key == "vcs.revision" {
				version = setting.Value
			}
		}
	}
	res, err := resource.New(ctx, resource.WithProcessPID(), resource.WithProcessRuntimeVersion(), resource.WithAttributes(
		attribute.String("service.name", name), attribute.String("service.version", version),
		attribute.String("service.instance.id", uuid.NewString()), attribute.String("deployment.environment.name", environment)), resource.WithFromEnv())
	if err != nil {
		return nil, err
	}
	// Use the resource values in logs too, including standard OTel environment overrides.
	logger := slog.Default()
	for _, key := range []attribute.Key{"service.name", "service.version", "service.instance.id", "deployment.environment.name"} {
		value, _ := res.Set().Value(key)
		logger = logger.With(string(key), value.AsString())
	}
	slog.SetDefault(slog.New(traceHandler{logger.Handler()}))
	otel.SetErrorHandler(otel.ErrorHandlerFunc(func(err error) { slog.Error("telemetry export failed", "error", err) }))
	if c.OTLPEndpoint == "" {
		return func(context.Context) error { return nil }, nil
	}
	endpoint, err := url.Parse(c.OTLPEndpoint)
	if err != nil || (endpoint.Scheme != "http" && endpoint.Scheme != "https") || endpoint.Host == "" || endpoint.User != nil || endpoint.RawQuery != "" || endpoint.Fragment != "" || math.IsNaN(c.TraceSampleRatio) || c.TraceSampleRatio < 0 || c.TraceSampleRatio > 1 || c.MetricsExportIntervalSeconds < 1 {
		return nil, fmt.Errorf("invalid telemetry endpoint, sample ratio or metrics interval")
	}
	te, err := otlptracegrpc.New(ctx, otlptracegrpc.WithEndpointURL(c.OTLPEndpoint), otlptracegrpc.WithTimeout(3*time.Second))
	if err != nil {
		return nil, err
	}
	me, err := otlpmetricgrpc.New(ctx, otlpmetricgrpc.WithEndpointURL(c.OTLPEndpoint), otlpmetricgrpc.WithTimeout(3*time.Second))
	if err != nil {
		_ = te.Shutdown(ctx)
		return nil, err
	}
	tp := trace.NewTracerProvider(trace.WithResource(res), trace.WithBatcher(te, trace.WithExportTimeout(3*time.Second)), trace.WithSampler(trace.ParentBased(trace.TraceIDRatioBased(c.TraceSampleRatio))))
	mp := metric.NewMeterProvider(metric.WithResource(res), metric.WithReader(metric.NewPeriodicReader(me, metric.WithInterval(time.Duration(c.MetricsExportIntervalSeconds)*time.Second), metric.WithTimeout(3*time.Second))))
	otel.SetTracerProvider(tp)
	otel.SetMeterProvider(mp)
	if err := otelruntime.Start(); err != nil {
		return nil, errors.Join(err, tp.Shutdown(ctx), mp.Shutdown(ctx))
	}
	return func(ctx context.Context) error { return errors.Join(tp.Shutdown(ctx), mp.Shutdown(ctx)) }, nil
}

type traceHandler struct{ slog.Handler }

func (h traceHandler) Handle(ctx context.Context, record slog.Record) error {
	span := traceapi.SpanContextFromContext(ctx)
	if span.IsValid() {
		record.AddAttrs(slog.String("trace_id", span.TraceID().String()), slog.String("span_id", span.SpanID().String()))
	}
	return h.Handler.Handle(ctx, record)
}
func (h traceHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return traceHandler{h.Handler.WithAttrs(attrs)}
}
func (h traceHandler) WithGroup(name string) slog.Handler {
	return traceHandler{h.Handler.WithGroup(name)}
}
