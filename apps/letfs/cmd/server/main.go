package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/exaring/otelpgx"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.opentelemetry.io/otel/propagation"
	"go.temporal.io/sdk/client"
	temporalotel "go.temporal.io/sdk/contrib/opentelemetry"
	"go.temporal.io/sdk/interceptor"
	temporalworker "go.temporal.io/sdk/worker"
	"golang.org/x/sync/semaphore"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"
	"openlet/apps/letfs/internal/config"
	"openlet/apps/letfs/internal/filesystem"
	handlers "openlet/apps/letfs/internal/grpc"
	httpapi "openlet/apps/letfs/internal/http"
	"openlet/apps/letfs/internal/search"
	"openlet/apps/letfs/internal/storage"
	"openlet/apps/letfs/internal/temporal"
	"openlet/packages/go/authz"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/rpc"
	"openlet/packages/go/telemetry"
)

func main() {
	if len(os.Args) == 2 && os.Args[1] == "--healthcheck" {
		response, err := (&http.Client{Timeout: 4 * time.Second}).Get("http://127.0.0.1:8080/ready")
		if err != nil {
			os.Exit(1)
		}
		defer response.Body.Close()
		if response.StatusCode != http.StatusNoContent {
			os.Exit(1)
		}
		return
	}
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	if err := run(ctx); err != nil {
		slog.Error("server failed", "reason", err.Error())
		os.Exit(1)
	}
}
func run(ctx context.Context) error {
	if len(os.Args) == 2 && os.Args[1] == "--provider-smoke" {
		cfg, err := config.Load()
		if err != nil {
			return err
		}
		return storage.ProviderSmoke(ctx, cfg.Storage)
	}
	backfill, err := backfillOptions(os.Args[1:])
	if err != nil {
		return err
	}
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	contract, err := authz.LoadContract("/contracts/schema.zed", "/contracts/roles.json")
	if err != nil {
		return err
	}
	if backfill != nil {
		return serve(ctx, cfg, contract, nil, backfill)
	}
	listener, err := net.Listen("tcp", cfg.RPCListen)
	if err != nil {
		return errors.New("RPC listener unavailable")
	}
	defer listener.Close()
	return serve(ctx, cfg, contract, listener, nil)
}
func authentication(cfg config.Config) (*rpc.Authenticator, error) {
	methods := func(descriptor grpcgo.ServiceDesc) []string {
		result := make([]string, 0, len(descriptor.Methods)+len(descriptor.Streams))
		for _, method := range descriptor.Methods {
			result = append(result, "/"+descriptor.ServiceName+"/"+method.MethodName)
		}
		for _, stream := range descriptor.Streams {
			result = append(result, "/"+descriptor.ServiceName+"/"+stream.StreamName)
		}
		return result
	}
	return rpc.NewAuthenticator([]rpc.Credential{
		{Service: "gateway", Token: cfg.GatewayToken, Gateway: true, Methods: methods(letfsv1.FilesystemService_ServiceDesc)},
		{Service: "workspace", Token: cfg.WorkspaceToken, Methods: methods(letfsv1.StorageAdministrationService_ServiceDesc)},
		{Service: "ingest", Token: cfg.IngestToken, Methods: methods(letfsv1.IngestService_ServiceDesc)},
	})
}

type readiness struct {
	healthv1.UnimplementedHealthServer
	check func(context.Context) error
}

func (r *readiness) Check(ctx context.Context, request *healthv1.HealthCheckRequest) (*healthv1.HealthCheckResponse, error) {
	if service := request.GetService(); service != "" && service != letfsv1.FilesystemService_ServiceDesc.ServiceName && service != letfsv1.StorageAdministrationService_ServiceDesc.ServiceName && service != letfsv1.IngestService_ServiceDesc.ServiceName {
		return nil, status.Error(codes.NotFound, "unknown service")
	}
	check, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	state := healthv1.HealthCheckResponse_SERVING
	if r.check(check) != nil {
		state = healthv1.HealthCheckResponse_NOT_SERVING
	}
	return &healthv1.HealthCheckResponse{Status: state}, nil
}

func serve(ctx context.Context, cfg config.Config, contract *authz.Contract, listener net.Listener, backfill *temporal.BackfillOptions) error {
	startup, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	stopTelemetry, err := telemetry.Init(startup, "openlet-letfs")
	if err != nil {
		return err
	}
	defer func() {
		stop, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if stopTelemetry(stop) != nil {
			slog.Warn("telemetry shutdown incomplete")
		}
	}()
	poolConfig, err := pgxpool.ParseConfig(cfg.DatabaseURL)
	if err != nil {
		return errors.New("database configuration rejected")
	}
	poolConfig.MaxConns = 16
	poolConfig.ConnConfig.Tracer = otelpgx.NewTracer(otelpgx.WithTrimSQLInSpanName(), otelpgx.WithDisableSQLStatementInAttributes(), otelpgx.WithDisableConnectionDetailsInAttributes())
	db, err := pgxpool.NewWithConfig(startup, poolConfig)
	if err != nil {
		return errors.New("database configuration rejected")
	}
	defer db.Close()
	if err = db.Ping(startup); err != nil {
		return errors.New("database unavailable")
	}
	connection, err := rpc.Dial(cfg.SpiceDBAddress, cfg.SpiceDBKey, rpc.Transport{AllowPlaintext: cfg.AllowPlaintextRPC})
	if err != nil {
		return errors.New("authorization transport configuration rejected")
	}
	defer connection.Close()
	graph := v1.NewPermissionsServiceClient(connection)
	graphReady := func(ctx context.Context) error {
		if err := db.Ping(ctx); err != nil {
			return err
		}
		return contract.Verify(ctx, v1.NewSchemaServiceClient(connection), graph)
	}
	if err = graphReady(startup); err != nil {
		return errors.New("authorization schema or role policy unavailable")
	}
	objects, err := storage.New(cfg.Storage)
	if err != nil {
		return err
	}
	store := &filesystem.Store{DB: db, Graph: graph, Storage: objects, MaxNodes: cfg.MaxNodes, MaxCopyNodes: cfg.MaxCopyNodes,
		InlineLimit: cfg.InlineLimit, MaxFileBytes: cfg.MaxFileBytes, DownloadLifetime: cfg.DownloadLifetime,
		MaxOutstanding: cfg.MaxOutstanding, MaxCleanupBacklog: cfg.MaxCleanupBacklog,
		MultipartThreshold: cfg.MultipartThreshold, MultipartPartBytes: cfg.MultipartPartBytes,
		UploadLifetime: cfg.UploadLifetime, UploadTransferGrace: cfg.UploadTransferGrace}
	store.ProcessingMaxOutputs, store.ProcessingMaxOutputBytes = cfg.ProcessingMaxOutputs, cfg.ProcessingMaxOutputBytes
	store.IndexSpace = cfg.IndexSpace
	store.Archive, store.ArchiveSlots = cfg.Archive, semaphore.NewWeighted(cfg.ArchiveMaxConcurrent)
	store.Search, err = search.New(cfg.QdrantURL, cfg.QdrantKey)
	if err != nil {
		return err
	}
	store.AI, err = search.NewAI(cfg.AI)
	if err != nil {
		return err
	}
	tracing, err := temporalotel.NewTracingInterceptor(temporalotel.TracerOptions{DisableBaggage: true, TextMapPropagator: propagation.TraceContext{}})
	if err != nil {
		return errors.New("Temporal tracing configuration rejected")
	}
	tc, err := client.DialContext(startup, client.Options{HostPort: cfg.TemporalAddress, Namespace: cfg.TemporalNamespace,
		Logger: slog.Default(), Interceptors: []interceptor.ClientInterceptor{tracing}, MetricsHandler: temporalotel.NewMetricsHandler(temporalotel.MetricsHandlerOptions{})})
	if err != nil {
		return errors.New("Temporal unavailable")
	}
	defer tc.Close()
	jobs := &temporal.Jobs{Client: tc}
	if backfill != nil {
		result, err := (&temporal.Activities{Store: store, Jobs: jobs}).Backfill(ctx, *backfill)
		if writeErr := json.NewEncoder(os.Stdout).Encode(result); writeErr != nil {
			return errors.New("backfill result output failed")
		}
		return err
	}
	owner := temporalworker.New(tc, temporal.Queue, temporalworker.Options{MaxConcurrentActivityExecutionSize: 16, WorkerStopTimeout: 20 * time.Second})
	temporal.Register(owner, &temporal.Activities{Store: store, Jobs: jobs})
	if err = owner.Start(); err != nil {
		return errors.New("worker startup failed")
	}
	defer owner.Stop()
	if err = temporal.EnsureSchedule(startup, tc); err != nil {
		return errors.New("maintenance schedule unavailable")
	}
	ready := func(ctx context.Context) error {
		if err := graphReady(ctx); err != nil {
			return err
		}
		_, err := tc.CheckHealth(ctx, &client.CheckHealthRequest{})
		return err
	}
	auth, err := authentication(cfg)
	if err != nil {
		return err
	}
	transport := rpc.Transport{AllowPlaintext: cfg.AllowPlaintextRPC}
	if !cfg.AllowPlaintextRPC {
		certificate, err := tls.LoadX509KeyPair(cfg.RPCCertificatePath, cfg.RPCPrivateKeyPath)
		if err != nil {
			return errors.New("RPC TLS certificate unavailable")
		}
		transport.TLS = &tls.Config{MinVersion: tls.VersionTLS12, Certificates: []tls.Certificate{certificate}}
	}
	server, err := rpc.NewServer(auth, transport)
	if err != nil {
		return err
	}
	defer server.Stop()
	public := &handlers.Filesystem{Store: store, Jobs: jobs}
	letfsv1.RegisterFilesystemServiceServer(server, public)
	letfsv1.RegisterStorageAdministrationServiceServer(server, &handlers.Administration{Store: store})
	letfsv1.RegisterIngestServiceServer(server, &handlers.Ingest{Store: store})
	healthv1.RegisterHealthServer(server, &readiness{check: ready})
	httpListener, err := net.Listen("tcp", cfg.Listen)
	if err != nil {
		return errors.New("HTTP listener unavailable")
	}
	defer httpListener.Close()
	publicHTTP := &http.Server{Handler: (&httpapi.Server{API: public, Store: store, GatewayToken: cfg.GatewayToken, Ready: ready}).Handler(), ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 120 * time.Second, MaxHeaderBytes: 32 * 1024}
	defer publicHTTP.Close()
	result := make(chan error, 2)
	go func() {
		err := publicHTTP.Serve(httpListener)
		if errors.Is(err, http.ErrServerClosed) {
			err = nil
		}
		result <- err
	}()
	go func() { result <- server.Serve(listener) }()
	slog.Info("gRPC listening", "address", listener.Addr().String())
	select {
	case err := <-result:
		return err
	case <-ctx.Done():
	}
	shutdown, cancelShutdown := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancelShutdown()
	stopped := make(chan struct{})
	go func() { server.GracefulStop(); close(stopped) }()
	if err := publicHTTP.Shutdown(shutdown); err != nil {
		_ = publicHTTP.Close()
	}
	timer := time.NewTimer(30 * time.Second)
	defer timer.Stop()
	select {
	case <-stopped:
	case <-timer.C:
		server.Stop()
		<-stopped
	}
	if err := <-result; err != nil {
		return err
	}
	return <-result
}
