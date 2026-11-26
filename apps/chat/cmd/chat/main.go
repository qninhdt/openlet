package main

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/qninhdt/openlet/apps/chat/internal/chat"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/chat/v1"
	letapb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/leta/v1"
	letfspb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"google.golang.org/grpc"
	"google.golang.org/grpc/health"
	healthpb "google.golang.org/grpc/health/grpc_health_v1"
)

func main() {
	if err := run(); err != nil {
		slog.Error("chat stopped", "error", err)
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
	var settings chat.Settings
	var runtime sdk.Runtime
	var telemetry sdk.Telemetry
	var g sdk.GRPC
	var postgres sdk.Postgres
	var graph sdk.SpiceDB
	var centrifugo sdk.Centrifugo
	var letfsTarget, letaGRPCTarget string

	for _, v := range []struct {
		path   string
		target any
	}{
		{"runtime", &runtime},
		{"telemetry", &telemetry},
		{"grpc", &g},
		{"services.chat", &settings},
		{"dependencies.postgres", &postgres},
		{"dependencies.spicedb", &graph},
		{"services.letfs.grpc_target", &letfsTarget},
	} {
		if err = c.Section(v.path, v.target); err != nil {
			return err
		}
	}
	if err = c.OptionalSection("dependencies.centrifugo", &centrifugo); err != nil {
		return err
	}
	if err = c.OptionalSection("services.leta.grpc_target", &letaGRPCTarget); err != nil {
		return err
	}
	if settings.GRPCListen == "" || g.MaxReceiveBytes < 1 || runtime.ShutdownTimeoutSeconds < 1 {
		return fmt.Errorf("invalid chat/runtime settings")
	}

	var level slog.Level
	if err = level.UnmarshalText([]byte(runtime.LogLevel)); err != nil {
		return err
	}
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: level})))

	shutdown, err := sdk.InitTelemetry(ctx, "openlet-chat", runtime.Environment, telemetry)
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

	letfsConn, err := sdk.Dial(letfsTarget)
	if err != nil {
		return err
	}
	defer letfsConn.Close()

	var letaInternal letapb.LetaInternalServiceClient
	if letaGRPCTarget != "" {
		letaConn, err := sdk.Dial(letaGRPCTarget)
		if err != nil {
			return err
		}
		defer letaConn.Close()
		letaInternal = letapb.NewLetaInternalServiceClient(letaConn)
	}

	var cenClient *chat.CentrifugoClient
	var cenSecret string
	cenTTL := time.Hour
	if centrifugo.TokenTTLSeconds > 0 {
		cenTTL = time.Duration(centrifugo.TokenTTLSeconds) * time.Second
	}
	if centrifugo.APIURL != "" {
		var apiKey string
		if centrifugo.APIKey != "" {
			apiKey, err = sdk.Secret("dependencies.centrifugo.api_key", centrifugo.APIKey)
			if err != nil {
				return err
			}
		}
		cenClient = &chat.CentrifugoClient{
			APIURL: centrifugo.APIURL,
			APIKey: apiKey,
			HTTP:   &http.Client{Timeout: 10 * time.Second, Transport: otelhttp.NewTransport(http.DefaultTransport)},
		}
	}
	if centrifugo.TokenHMACSecret != "" {
		cenSecret, err = sdk.Secret("dependencies.centrifugo.token_hmac_secret", centrifugo.TokenHMACSecret)
		if err != nil {
			return err
		}
	}

	app := &chat.Server{
		DB:               db,
		Graph:            az,
		LetFS:            letfspb.NewLetFSServiceClient(letfsConn),
		LetFSInternal:    letfspb.NewLetFSInternalServiceClient(letfsConn),
		LetaInternal:     letaInternal,
		Centrifugo:       cenClient,
		CentrifugoSecret: cenSecret,
		CentrifugoTTL:    cenTTL,
		Settings:         settings,
	}

	outboxCtx, stopOutbox := context.WithCancel(ctx)
	outboxDone := make(chan struct{})
	go func() {
		defer close(outboxDone)
		app.RunOutboxWorker(outboxCtx)
	}()

	validate, err := sdk.Validation()
	if err != nil {
		stopOutbox()
		return err
	}
	server := grpc.NewServer(
		grpc.MaxRecvMsgSize(g.MaxReceiveBytes),
		grpc.UnaryInterceptor(validate),
		grpc.StatsHandler(otelgrpc.NewServerHandler()),
	)
	pb.RegisterChatServiceServer(server, app)
	pb.RegisterChatInternalServiceServer(server, app)
	h := health.NewServer()
	healthpb.RegisterHealthServer(server, h)
	h.SetServingStatus("", healthpb.HealthCheckResponse_SERVING)

	listener, err := net.Listen("tcp", settings.GRPCListen)
	if err != nil {
		stopOutbox()
		return err
	}
	defer listener.Close()

	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	slog.Info("chat ready", "address", settings.GRPCListen)

	select {
	case err := <-done:
		stopOutbox()
		<-outboxDone
		return err
	case <-ctx.Done():
	}

	h.Shutdown()
	stopOutbox()
	drained := make(chan struct{})
	go func() { server.GracefulStop(); close(drained) }()
	timer := time.NewTimer(time.Duration(runtime.ShutdownTimeoutSeconds) * time.Second)
	defer timer.Stop()
	select {
	case <-drained:
	case <-timer.C:
		server.Stop()
	}
	<-outboxDone
	err = <-done
	if errors.Is(err, grpc.ErrServerStopped) {
		return nil
	}
	return err
}
