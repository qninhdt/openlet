package main

import (
	"context"
	"crypto/tls"
	"errors"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/exaring/otelpgx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/qninhdt/openlet/apps/workspace/internal/config"
	jobs "github.com/qninhdt/openlet/apps/workspace/internal/temporal"
	workspaceRPC "github.com/qninhdt/openlet/apps/workspace/internal/transport/grpc"
	api "github.com/qninhdt/openlet/apps/workspace/internal/transport/http"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/qninhdt/openlet/packages/go/authz"
	accountclient "github.com/qninhdt/openlet/packages/go/clients/account"
	letaclient "github.com/qninhdt/openlet/packages/go/clients/leta"
	letfsclient "github.com/qninhdt/openlet/packages/go/clients/letfs"
	accountv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/account/v1"
	letav1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/leta/v1"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	workspacev1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/workspace/v1"
	sharedrpc "github.com/qninhdt/openlet/packages/go/rpc"
	"github.com/qninhdt/openlet/packages/go/telemetry"
	sharedtemporal "github.com/qninhdt/openlet/packages/go/temporal"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/interceptor"
	temporalworker "go.temporal.io/sdk/worker"
	"google.golang.org/grpc"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	if len(os.Args) == 2 && os.Args[1] == "--healthcheck" {
		res, e := (&http.Client{Timeout: 4 * time.Second}).Get("http://127.0.0.1:8080/ready")
		if e != nil {
			os.Exit(1)
		}
		defer res.Body.Close()
		if res.StatusCode != 204 {
			os.Exit(1)
		}
		return
	}
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	if e := run(); e != nil {
		slog.Error("server failed", "reason", e.Error())
		os.Exit(1)
	}
}
func run() error {
	gin.SetMode(gin.ReleaseMode)
	startupTelemetry, cancelTelemetry := context.WithTimeout(context.Background(), 5*time.Second)
	shutdownTelemetry, telemetryError := telemetry.Init(startupTelemetry, "openlet-workspace")
	cancelTelemetry()
	if telemetryError != nil {
		return telemetryError
	}
	defer func() {
		stop, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if shutdownTelemetry(stop) != nil {
			slog.Warn("telemetry shutdown incomplete")
		}
	}()
	cfg, e := config.Load()
	if e != nil {
		return e
	}
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	poolConfig, e := pgxpool.ParseConfig(cfg.DatabaseURL)
	if e != nil {
		return errors.New("database configuration rejected")
	}
	poolConfig.MaxConns = 16
	poolConfig.ConnConfig.Tracer = otelpgx.NewTracer(otelpgx.WithTrimSQLInSpanName(), otelpgx.WithDisableSQLStatementInAttributes(), otelpgx.WithDisableConnectionDetailsInAttributes())
	db, e := pgxpool.NewWithConfig(ctx, poolConfig)
	if e != nil {
		return errors.New("database configuration rejected")
	}
	defer db.Close()
	startupCtx, startupCancel := context.WithTimeout(ctx, 10*time.Second)
	defer startupCancel()
	if e = db.Ping(startupCtx); e != nil {
		return errors.New("database unavailable")
	}
	if len(os.Args) == 2 && os.Args[1] == "--export-resource-workspaces" {
		return (&workspace.Store{DB: db}).ExportResourceWorkspaces(ctx, os.Stdout)
	}
	graphConnection, e := sharedrpc.Dial(cfg.SpiceDBAddress, cfg.SpiceDBKey, sharedrpc.Transport{AllowPlaintext: cfg.AllowPlaintextRPC})
	if e != nil {
		return errors.New("authorization transport configuration rejected")
	}
	defer graphConnection.Close()
	graph := v1.NewPermissionsServiceClient(graphConnection)
	contract, e := authz.LoadContract("/contracts/schema.zed")
	if e != nil {
		return e
	}
	graphReady := func(ctx context.Context) error {
		return contract.Verify(ctx, v1.NewSchemaServiceClient(graphConnection))
	}
	if e = graphReady(startupCtx); e != nil {
		return errors.New("authorization schema unavailable")
	}
	store := &workspace.Store{DB: db, Graph: graph, MaxMembers: cfg.MaxMembers, InviteTTL: cfg.InviteTTL}
	if len(os.Args) == 2 && os.Args[1] == "--rebuild-authorization" {
		return store.RebuildRelationships(ctx, graph)
	}
	tracing, e := sharedtemporal.Tracing()
	if e != nil {
		return errors.New("Temporal tracing configuration rejected")
	}
	tc, e := client.DialContext(startupCtx, client.Options{HostPort: cfg.TemporalAddress, Namespace: cfg.TemporalNamespace, Logger: slog.Default(), Interceptors: []interceptor.ClientInterceptor{tracing}})
	if e != nil {
		return errors.New("Temporal unavailable")
	}
	defer tc.Close()
	accountConnection, e := sharedrpc.Dial(cfg.AccountRPCAddress, cfg.WorkspaceToken, sharedrpc.Transport{AllowPlaintext: cfg.AllowPlaintextRPC})
	if e != nil {
		return e
	}
	defer accountConnection.Close()
	accountHealth, e := healthv1.NewHealthClient(accountConnection).Check(startupCtx, &healthv1.HealthCheckRequest{Service: accountv1.AccountService_ServiceDesc.ServiceName}, grpc.WaitForReady(true))
	if e != nil || accountHealth.GetStatus() != healthv1.HealthCheckResponse_SERVING {
		return errors.New("User RPC unavailable")
	}
	accountClient := accountclient.Client{API: accountv1.NewAccountServiceClient(accountConnection)}
	storageConnection, e := sharedrpc.Dial(cfg.LetFSRPCAddress, cfg.WorkspaceToken, sharedrpc.Transport{AllowPlaintext: cfg.AllowPlaintextRPC})
	if e != nil {
		return e
	}
	defer storageConnection.Close()
	letaConnection, e := sharedrpc.Dial(cfg.LetaRPCAddress, cfg.WorkspaceToken, sharedrpc.Transport{AllowPlaintext: cfg.AllowPlaintextRPC})
	if e != nil {
		return e
	}
	defer letaConnection.Close()
	letaClient := letaclient.Client{API: letav1.NewLetaServiceClient(letaConnection)}
	service := &workspace.Service{Store: store, Users: accountClient,
		Storage: letfsclient.Client{API: letfsv1.NewStorageAdministrationServiceClient(storageConnection)},
		Homes:   letfsclient.Client{API: letfsv1.NewStorageAdministrationServiceClient(storageConnection)},
		Letas:   letaClient}
	service.StartCreate = func(ctx context.Context, in workspace.CreateInput) (workspace.Workspace, error) {
		return jobs.StartCreate(ctx, tc, in)
	}
	service.Mutate = func(ctx context.Context, in workspace.Mutation) (workspace.Workspace, error) {
		return jobs.Mutate(ctx, tc, in)
	}
	activities := &jobs.Activities{Service: service, Letas: letaClient}
	owner := temporalworker.New(tc, jobs.Queue, temporalworker.Options{MaxConcurrentActivityExecutionSize: 16, WorkerStopTimeout: 20 * time.Second})
	workflows := &jobs.Workflows{QuotaLimit: cfg.QuotaLimit}
	owner.RegisterWorkflow(workflows.CreateWorkspace)
	owner.RegisterWorkflow(jobs.DeleteWorkspace)
	owner.RegisterWorkflow(jobs.WorkspaceMaintenance)
	owner.RegisterWorkflow(jobs.WorkspaceChanges)
	owner.RegisterActivity(activities)
	if e = owner.Start(); e != nil {
		return errors.New("worker startup failed")
	}
	defer owner.Stop()
	if e = jobs.EnsureMaintenance(startupCtx, tc); e != nil {
		return errors.New("maintenance schedule unavailable")
	}
	app := &api.Server{Config: cfg, Service: service, Ready: func(ctx context.Context) error {
		if err := db.Ping(ctx); err != nil {
			return err
		}
		return graphReady(ctx)
	}}

	authentication, e := sharedrpc.NewAuthenticator([]sharedrpc.Credential{workspaceRPC.Credential(cfg.LetaToken)})
	if e != nil {
		return e
	}
	transport := sharedrpc.Transport{AllowPlaintext: cfg.AllowPlaintextRPC}
	if !cfg.AllowPlaintextRPC {
		certificate, err := tls.LoadX509KeyPair(cfg.RPCCertificatePath, cfg.RPCPrivateKeyPath)
		if err != nil {
			return errors.New("RPC TLS certificate unavailable")
		}
		transport.TLS = &tls.Config{MinVersion: tls.VersionTLS12, Certificates: []tls.Certificate{certificate}}
	}
	rpcServer, e := sharedrpc.NewServer(authentication, transport)
	if e != nil {
		return e
	}
	defer rpcServer.Stop()
	rpcHandler := &workspaceRPC.Server{Service: service, Ready: app.Ready}
	workspacev1.RegisterWorkspaceServiceServer(rpcServer, rpcHandler)
	healthv1.RegisterHealthServer(rpcServer, rpcHandler)
	rpcListener, e := net.Listen("tcp", cfg.RPCListen)
	if e != nil {
		return errors.New("RPC listener unavailable")
	}
	defer rpcListener.Close()
	srv := &http.Server{Addr: cfg.Listen, Handler: app.Router(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 125 * time.Second, WriteTimeout: 125 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 32768}
	defer srv.Close()
	errch := make(chan error, 2)
	go func() { slog.Info("gRPC listening", "address", cfg.RPCListen); errch <- rpcServer.Serve(rpcListener) }()
	go func() { slog.Info("HTTP listening", "address", cfg.Listen); errch <- srv.ListenAndServe() }()
	select {
	case e = <-errch:
		if e != http.ErrServerClosed {
			return e
		}
	case <-ctx.Done():
	}
	stopCtx, stop := context.WithTimeout(context.Background(), 125*time.Second)
	defer stop()
	e = srv.Shutdown(stopCtx)
	rpcStopped := make(chan struct{})
	go func() { rpcServer.GracefulStop(); close(rpcStopped) }()
	select {
	case <-rpcStopped:
	case <-stopCtx.Done():
		rpcServer.Stop()
		<-rpcStopped
	}
	return e
}
