package main

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	clerk "github.com/clerk/clerk-sdk-go/v2"
	"github.com/clerk/clerk-sdk-go/v2/user"
	"github.com/qninhdt/openlet/apps/platform/internal/platform"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/platform/v1"
	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
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

func main() {
	if err := run(); err != nil {
		slog.Error("platform stopped", "error", err)
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
	var settings platform.Settings
	var runtime sdk.Runtime
	var telemetry sdk.Telemetry
	var g sdk.GRPC
	var postgres sdk.Postgres
	var graph sdk.SpiceDB
	var temporal sdk.Temporal
	var clerkURL, clerkKey string
	for _, v := range []struct {
		path   string
		target any
	}{{"runtime", &runtime}, {"telemetry", &telemetry}, {"grpc", &g}, {"services.platform", &settings}, {"dependencies.postgres", &postgres}, {"dependencies.spicedb", &graph}, {"dependencies.temporal", &temporal}, {"auth.clerk.api_url", &clerkURL}, {"auth.clerk.secret_key", &clerkKey}} {
		if err = c.Section(v.path, v.target); err != nil {
			return err
		}
	}
	if settings.GRPCListen == "" || settings.MaxMembers < 1 || settings.DefaultQuotaBytes < 0 || settings.InvitationTTLSeconds < 1 || settings.IdempotencyRetentionSeconds < 1 || g.MaxReceiveBytes < 1 || runtime.ShutdownTimeoutSeconds < 1 || temporal.Queues.Platform == "" {
		return fmt.Errorf("invalid platform/runtime settings")
	}
	var level slog.Level
	if err = level.UnmarshalText([]byte(runtime.LogLevel)); err != nil {
		return err
	}
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: level})))
	shutdown, err := sdk.InitTelemetry(ctx, "openlet-platform", runtime.Environment, telemetry)
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
	tracing, err := temporalotel.NewTracingInterceptor(temporalotel.TracerOptions{DisableBaggage: true, TextMapPropagator: propagation.TraceContext{}})
	if err != nil {
		return err
	}
	options := client.Options{HostPort: temporal.Address, Namespace: temporal.Namespace, Logger: log.NewStructuredLogger(slog.Default()), Interceptors: []interceptor.ClientInterceptor{tracing}, MetricsHandler: temporalotel.NewMetricsHandler(temporalotel.MetricsHandlerOptions{})}
	if temporal.TLS {
		options.ConnectionOptions.TLS = &tls.Config{MinVersion: tls.VersionTLS12}
	}
	tc, err := client.Dial(options)
	if err != nil {
		return err
	}
	defer tc.Close()
	key, err := sdk.Secret("auth.clerk.secret_key", clerkKey)
	if err != nil {
		return err
	}
	app := &platform.Server{DB: db, Graph: az, Clerk: user.NewClient(&clerk.ClientConfig{BackendConfig: clerk.BackendConfig{URL: &clerkURL, Key: &key, HTTPClient: &http.Client{Transport: otelhttp.NewTransport(http.DefaultTransport)}}}), Temporal: tc, Settings: settings, Queue: temporal.Queues.Platform, Queues: temporal.Queues}
	w := worker.New(tc, temporal.Queues.Platform, worker.Options{WorkerStopTimeout: time.Duration(runtime.ShutdownTimeoutSeconds) * time.Second})
	platform.RegisterWorker(w, app)
	if err = w.Start(); err != nil {
		return err
	}
	defer w.Stop()
	validate, err := sdk.Validation()
	if err != nil {
		return err
	}
	server := grpc.NewServer(grpc.MaxRecvMsgSize(g.MaxReceiveBytes), grpc.UnaryInterceptor(validate), grpc.StatsHandler(otelgrpc.NewServerHandler()))
	pb.RegisterPlatformServiceServer(server, app)
	pb.RegisterPlatformInternalServiceServer(server, app)
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
	slog.Info("platform ready", "address", settings.GRPCListen)
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
