package telemetry

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"strconv"
	"time"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetricgrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
)

// Init owns the providers; callers shut them down after HTTP and workers drain.
func Init(ctx context.Context, service string) (func(context.Context) error, error) {
	disabled := os.Getenv("OTEL_SDK_DISABLED") == "true"
	resourceOptions := []resource.Option{resource.WithTelemetrySDK(),
		resource.WithAttributes(attribute.String("service.name", service), attribute.String("service.version", "development"))}
	if !disabled {
		resourceOptions = append(resourceOptions, resource.WithFromEnv())
	}
	res, err := resource.New(ctx, resourceOptions...)
	if err != nil {
		return nil, errors.New("telemetry resource configuration rejected")
	}
	sampler := sdktrace.Sampler(sdktrace.NeverSample())
	if !disabled {
		sampler, err = configuredSampler()
		if err != nil {
			return nil, err
		}
	}
	traceOptions := []sdktrace.TracerProviderOption{sdktrace.WithResource(res), sdktrace.WithSampler(sampler)}
	metricOptions := []metric.Option{metric.WithResource(res)}
	if !disabled {
		if endpoint("TRACES") && os.Getenv("OTEL_TRACES_EXPORTER") != "none" {
			var exporter sdktrace.SpanExporter
			switch protocol("TRACES") {
			case "grpc":
				exporter, err = otlptracegrpc.New(ctx, otlptracegrpc.WithTimeout(3*time.Second))
			case "http/protobuf":
				exporter, err = otlptracehttp.New(ctx, otlptracehttp.WithTimeout(3*time.Second))
			default:
				return nil, errors.New("unsupported OTLP traces protocol")
			}
			if err != nil {
				return nil, errors.New("telemetry traces configuration rejected")
			}
			traceOptions = append(traceOptions, sdktrace.WithBatcher(exporter,
				sdktrace.WithMaxQueueSize(1024), sdktrace.WithMaxExportBatchSize(256),
				sdktrace.WithExportTimeout(3*time.Second)))
		}
	}
	tp := sdktrace.NewTracerProvider(traceOptions...)
	if !disabled && endpoint("METRICS") && os.Getenv("OTEL_METRICS_EXPORTER") != "none" {
		var exporter metric.Exporter
		switch protocol("METRICS") {
		case "grpc":
			exporter, err = otlpmetricgrpc.New(ctx, otlpmetricgrpc.WithTimeout(3*time.Second))
		case "http/protobuf":
			exporter, err = otlpmetrichttp.New(ctx, otlpmetrichttp.WithTimeout(3*time.Second))
		default:
			err = errors.New("unsupported OTLP metrics protocol")
		}
		if err != nil {
			stop, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			_ = tp.Shutdown(stop)
			return nil, errors.New("telemetry metrics configuration rejected")
		}
		metricOptions = append(metricOptions, metric.WithReader(metric.NewPeriodicReader(exporter,
			metric.WithInterval(30*time.Second), metric.WithTimeout(3*time.Second))))
	}
	mp := metric.NewMeterProvider(metricOptions...)
	otel.SetTracerProvider(tp)
	otel.SetMeterProvider(mp)
	otel.SetTextMapPropagator(propagation.TraceContext{})
	// Exporter diagnostics can contain endpoint credentials; keep them out of logs.
	otel.SetErrorHandler(otel.ErrorHandlerFunc(func(error) { slog.Warn("telemetry export failed") }))
	slog.SetDefault(slog.New(logHandler{slog.NewJSONHandler(os.Stdout, nil)}))
	return func(ctx context.Context) error { return errors.Join(mp.Shutdown(ctx), tp.Shutdown(ctx)) }, nil
}

func endpoint(signal string) bool {
	return os.Getenv("OTEL_EXPORTER_OTLP_"+signal+"_ENDPOINT") != "" || os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT") != ""
}

func protocol(signal string) string {
	if value := os.Getenv("OTEL_EXPORTER_OTLP_" + signal + "_PROTOCOL"); value != "" {
		return value
	}
	if value := os.Getenv("OTEL_EXPORTER_OTLP_PROTOCOL"); value != "" {
		return value
	}
	return "grpc"
}

func configuredSampler() (sdktrace.Sampler, error) {
	name := os.Getenv("OTEL_TRACES_SAMPLER")
	var sampler sdktrace.Sampler
	switch name {
	case "", "parentbased_always_on", "always_on":
		sampler = sdktrace.AlwaysSample()
	case "parentbased_always_off", "always_off":
		sampler = sdktrace.NeverSample()
	case "parentbased_traceidratio", "traceidratio":
		ratio, err := strconv.ParseFloat(os.Getenv("OTEL_TRACES_SAMPLER_ARG"), 64)
		if err != nil || !(ratio >= 0 && ratio <= 1) {
			return nil, errors.New("OTEL_TRACES_SAMPLER_ARG must be between zero and one")
		}
		sampler = sdktrace.TraceIDRatioBased(ratio)
	default:
		return nil, errors.New("unsupported OTEL_TRACES_SAMPLER")
	}
	if name == "" || name == "parentbased_always_on" || name == "parentbased_always_off" || name == "parentbased_traceidratio" {
		sampler = sdktrace.ParentBased(sampler)
	}
	return sampler, nil
}

type logHandler struct{ slog.Handler }

func (h logHandler) Handle(ctx context.Context, record slog.Record) error {
	span := trace.SpanContextFromContext(ctx)
	if span.IsValid() {
		record.AddAttrs(slog.String("trace_id", span.TraceID().String()), slog.String("span_id", span.SpanID().String()))
	}
	return h.Handler.Handle(ctx, record)
}

func (h logHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	return logHandler{h.Handler.WithAttrs(attrs)}
}

func (h logHandler) WithGroup(name string) slog.Handler {
	return logHandler{h.Handler.WithGroup(name)}
}
