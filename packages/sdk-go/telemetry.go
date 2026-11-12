package sdk

import (
	"context"
	"errors"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	"go.opentelemetry.io/otel/sdk/trace"
	"time"
)

type Telemetry struct {
	OTLPEndpoint                 string  `yaml:"otlp_endpoint"`
	TraceSampleRatio             float64 `yaml:"trace_sample_ratio"`
	MetricsExportIntervalSeconds int     `yaml:"metrics_export_interval_seconds"`
}

func InitTelemetry(ctx context.Context, name, environment string, c Telemetry) (func(context.Context) error, error) {
	otel.SetTextMapPropagator(propagation.TraceContext{})
	if c.OTLPEndpoint == "" {
		return func(context.Context) error { return nil }, nil
	}
	res, err := resource.New(ctx, resource.WithFromEnv(), resource.WithProcess(), resource.WithAttributes(attribute.String("service.name", name), attribute.String("deployment.environment.name", environment)))
	if err != nil {
		return nil, err
	}
	te, err := otlptracegrpc.New(ctx, otlptracegrpc.WithEndpointURL(c.OTLPEndpoint))
	if err != nil {
		return nil, err
	}
	me, err := otlpmetricgrpc.New(ctx, otlpmetricgrpc.WithEndpointURL(c.OTLPEndpoint))
	if err != nil {
		_ = te.Shutdown(ctx)
		return nil, err
	}
	tp := trace.NewTracerProvider(trace.WithResource(res), trace.WithBatcher(te), trace.WithSampler(trace.ParentBased(trace.TraceIDRatioBased(c.TraceSampleRatio))))
	mp := metric.NewMeterProvider(metric.WithResource(res), metric.WithReader(metric.NewPeriodicReader(me, metric.WithInterval(time.Duration(c.MetricsExportIntervalSeconds)*time.Second))))
	otel.SetTracerProvider(tp)
	otel.SetMeterProvider(mp)
	return func(ctx context.Context) error { return errors.Join(tp.Shutdown(ctx), mp.Shutdown(ctx)) }, nil
}
