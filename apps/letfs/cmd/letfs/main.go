package main

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/smithy-go/metrics/smithyotelmetrics"
	"github.com/aws/smithy-go/tracing/smithyoteltracing"
	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/option"
	"github.com/qdrant/go-client/qdrant"
	"github.com/qninhdt/openlet/apps/letfs/internal/storage"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	"go.temporal.io/sdk/client"
	temporalotel "go.temporal.io/sdk/contrib/opentelemetry"
	"go.temporal.io/sdk/interceptor"
	"go.temporal.io/sdk/log"
	"go.temporal.io/sdk/worker"
	"google.golang.org/grpc"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
)

type s3Settings struct {
	Endpoint        string `yaml:"endpoint"`
	Region          string `yaml:"region"`
	Bucket          string `yaml:"bucket"`
	PathStyle       bool   `yaml:"path_style"`
	AccessKeyID     string `yaml:"access_key_id"`
	SecretAccessKey string `yaml:"secret_access_key"`
}
type qdrantSettings struct {
	Address    string `yaml:"address"`
	TLS        bool   `yaml:"tls"`
	APIKey     string `yaml:"api_key"`
	Collection string `yaml:"collection"`
}

func main() {
	if err := run(); err != nil {
		slog.Error("letfs stopped", "error", err)
		os.Exit(1)
	}
}
func run() error {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	c, err := sdk.LoadConfig()
	if err != nil {
		return err
	}
	var settings storage.Settings
	var runtime sdk.Runtime
	var telemetry sdk.Telemetry
	var g sdk.GRPC
	var postgres sdk.Postgres
	var graph sdk.SpiceDB
	var temporal sdk.Temporal
	var object s3Settings
	var vector qdrantSettings
	var providerURL, providerKey, embedding, reranking string
	var dimensions int64
	for _, v := range []struct {
		path   string
		target any
	}{{"runtime", &runtime}, {"telemetry", &telemetry}, {"grpc", &g}, {"services.letfs", &settings}, {"dependencies.postgres", &postgres}, {"dependencies.spicedb", &graph}, {"dependencies.temporal", &temporal}, {"dependencies.s3", &object}, {"dependencies.qdrant", &vector}, {"models.provider.base_url", &providerURL}, {"models.provider.api_key", &providerKey}, {"models.embedding.model", &embedding}, {"models.embedding.dimensions", &dimensions}, {"models.reranking.model", &reranking}} {
		if err = c.Section(v.path, v.target); err != nil {
			return err
		}
	}
	if settings.GRPCListen == "" || settings.MaxTextBytes < 1 || settings.MaxBlobBytes < 1 || settings.MultipartPartBytes < 5*1024*1024 || settings.MultipartThresholdBytes < settings.MultipartPartBytes || settings.UploadURLTTLSeconds < 1 || settings.DownloadURLTTLSeconds < 1 || settings.IdempotencyRetentionSeconds < 1 || settings.Processing.MaxArtifacts < 1 || settings.Processing.MaxManifestTextBytes < 1 || settings.Processing.ParseTimeoutSeconds < 1 || settings.Processing.EnrichIndexTimeoutSeconds < 1 || settings.Maintenance.IntervalSeconds < 1 || settings.Maintenance.ObjectGCGraceSeconds <= settings.UploadURLTTLSeconds || g.MaxReceiveBytes < 1 || runtime.ShutdownTimeoutSeconds < 1 {
		return fmt.Errorf("invalid letfs/runtime settings")
	}
	var level slog.Level
	if err = level.UnmarshalText([]byte(runtime.LogLevel)); err != nil {
		return err
	}
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: level})))
	shutdown, err := sdk.InitTelemetry(ctx, "openlet-letfs", runtime.Environment, telemetry)
	if err != nil {
		return err
	}
	defer func() {
		flush, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = shutdown(flush)
	}()
	db, err := sdk.OpenDatabase(ctx, postgres, settings.Database)
	if err != nil {
		return err
	}
	defer db.Close()
	az, err := sdk.OpenSpiceDB(graph)
	if err != nil {
		return err
	}
	defer az.Close()
	key, err := sdk.Secret("dependencies.s3.access_key_id", object.AccessKeyID)
	if err != nil {
		return err
	}
	secret, err := sdk.Secret("dependencies.s3.secret_access_key", object.SecretAccessKey)
	if err != nil {
		return err
	}
	endpoint, err := url.ParseRequestURI(object.Endpoint)
	if err != nil || endpoint.Host == "" {
		return fmt.Errorf("invalid S3 endpoint")
	}
	s3client := s3.New(s3.Options{TracerProvider: smithyoteltracing.Adapt(otel.GetTracerProvider()), MeterProvider: smithyotelmetrics.Adapt(otel.GetMeterProvider()), Region: object.Region, BaseEndpoint: &object.Endpoint, UsePathStyle: object.PathStyle, Credentials: credentials.NewStaticCredentialsProvider(key, secret, "")})
	host, portText, err := net.SplitHostPort(vector.Address)
	if err != nil {
		return err
	}
	port, err := strconv.Atoi(portText)
	if err != nil {
		return err
	}
	vectorKey, err := sdk.Secret("dependencies.qdrant.api_key", vector.APIKey)
	if err != nil {
		return err
	}
	qc, err := qdrant.NewClient(&qdrant.Config{Host: host, Port: port, APIKey: vectorKey, UseTLS: vector.TLS, GrpcOptions: []grpc.DialOption{grpc.WithStatsHandler(otelgrpc.NewClientHandler())}})
	if err != nil {
		return err
	}
	defer qc.Close()
	modelKey, err := sdk.Secret("models.provider.api_key", providerKey)
	if err != nil {
		return err
	}
	models := openai.NewClient(option.WithAPIKey(modelKey), option.WithBaseURL(providerURL), option.WithHTTPClient(&http.Client{Transport: otelhttp.NewTransport(http.DefaultTransport)}))
	tracing, err := temporalotel.NewTracingInterceptor(temporalotel.TracerOptions{DisableBaggage: true, TextMapPropagator: propagation.TraceContext{}})
	if err != nil {
		return err
	}
	opts := client.Options{HostPort: temporal.Address, Namespace: temporal.Namespace, Logger: log.NewStructuredLogger(slog.Default()), Interceptors: []interceptor.ClientInterceptor{tracing}, MetricsHandler: temporalotel.NewMetricsHandler(temporalotel.MetricsHandlerOptions{})}
	if temporal.TLS {
		opts.ConnectionOptions.TLS = &tls.Config{MinVersion: tls.VersionTLS12}
	}
	tc, err := client.Dial(opts)
	if err != nil {
		return err
	}
	defer tc.Close()
	app := &storage.Server{DB: db, Graph: az, S3: s3client, Presign: s3.NewPresignClient(s3client), Bucket: object.Bucket, Temporal: tc, Queues: temporal.Queues, Settings: settings, Qdrant: qc, Collection: vector.Collection, Models: models, EmbeddingModel: embedding, EmbeddingDimensions: dimensions, RerankingModel: reranking}
	w := worker.New(tc, temporal.Queues.LetFS, worker.Options{WorkerStopTimeout: time.Duration(runtime.ShutdownTimeoutSeconds) * time.Second})
	storage.RegisterWorker(w, app)
	if err = w.Start(); err != nil {
		return err
	}
	defer w.Stop()
	validate, err := sdk.Validation()
	if err != nil {
		return err
	}
	server := grpc.NewServer(grpc.MaxRecvMsgSize(g.MaxReceiveBytes), grpc.UnaryInterceptor(validate), grpc.StatsHandler(otelgrpc.NewServerHandler()))
	pb.RegisterLetFSServiceServer(server, app)
	pb.RegisterLetFSInternalServiceServer(server, app)
	h := health.NewServer()
	healthpb.RegisterHealthServer(server, h)
	h.SetServingStatus("", healthpb.HealthCheckResponse_SERVING)
	listener, err := net.Listen("tcp", settings.GRPCListen)
	if err != nil {
		return err
	}
	defer listener.Close()
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	slog.Info("letfs ready", "address", settings.GRPCListen)
	select {
	case err := <-done:
		return err
	case <-ctx.Done():
	}
	h.Shutdown()
	drained := make(chan struct{})
	go func() { server.GracefulStop(); close(drained) }()
	timer := time.NewTimer(time.Duration(runtime.ShutdownTimeoutSeconds) * time.Second)
	defer timer.Stop()
	select {
	case <-drained:
	case <-timer.C:
		server.Stop()
	}
	err = <-done
	if errors.Is(err, grpc.ErrServerStopped) {
		return nil
	}
	return err
}
