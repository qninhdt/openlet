package main

import (
	"context"
	"crypto/tls"
	"errors"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/exaring/otelpgx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/qninhdt/openlet/apps/account/internal/clients/clerk"
	"github.com/qninhdt/openlet/apps/account/internal/config"
	jobs "github.com/qninhdt/openlet/apps/account/internal/temporal"
	accountRPC "github.com/qninhdt/openlet/apps/account/internal/transport/grpc"
	api "github.com/qninhdt/openlet/apps/account/internal/transport/http"
	"github.com/qninhdt/openlet/apps/account/internal/user"
	"github.com/qninhdt/openlet/packages/go/authz"
	workspaceclient "github.com/qninhdt/openlet/packages/go/clients/workspace"
	accountv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/account/v1"
	workspacev1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/workspace/v1"
	sharedrpc "github.com/qninhdt/openlet/packages/go/rpc"
	"github.com/qninhdt/openlet/packages/go/telemetry"
	sharedtemporal "github.com/qninhdt/openlet/packages/go/temporal"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/interceptor"
	temporalworker "go.temporal.io/sdk/worker"
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
	shutdownTelemetry, telemetryError := telemetry.Init(startupTelemetry, "openlet-account")
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
	graphConnection, e := sharedrpc.Dial(cfg.SpiceDBAddress, cfg.SpiceDBKey, sharedrpc.Transport{AllowPlaintext: cfg.AllowPlaintextRPC})
	if e != nil {
		return errors.New("authorization transport configuration rejected")
	}
	defer graphConnection.Close()
	graph := v1.NewPermissionsServiceClient(graphConnection)
	contract, e := authz.LoadContract("/contracts/schema.zed", "/contracts/roles.json")
	if e != nil {
		return e
	}
	graphReady := func(ctx context.Context) error {
		return contract.Verify(ctx, v1.NewSchemaServiceClient(graphConnection), graph)
	}
	if e = graphReady(startupCtx); e != nil {
		return errors.New("authorization schema or role policy unavailable")
	}
	store := &user.Store{DB: db}
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
	workspaceConnection, e := sharedrpc.Dial(cfg.WorkspaceRPCAddress, cfg.AccountToken, sharedrpc.Transport{AllowPlaintext: cfg.AllowPlaintextRPC})
	if e != nil {
		return e
	}
	defer workspaceConnection.Close()
	clerkClient := clerk.Client{BaseURL: cfg.ClerkURL, Secret: cfg.ClerkSecret}
	service := &user.Service{Store: store, Graph: graph, Clerk: clerkClient, Workspace: workspaceclient.Client{API: workspacev1.NewWorkspaceAdministrationServiceClient(workspaceConnection)}}
	service.StartOnboarding = func(ctx context.Context, subject string) (user.Onboarding, error) {
		return jobs.StartOnboarding(ctx, tc, subject)
	}
	authentication, e := sharedrpc.NewAuthenticator([]sharedrpc.Credential{{
		Service: "workspace", Token: cfg.WorkspaceToken,
		Methods: []string{accountv1.AccountService_GetUserSummaries_FullMethodName, accountv1.AccountService_GetVerifiedEmails_FullMethodName},
	}})
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
	rpcHandler := &accountRPC.Server{GraphReady: graphReady, Service: service}
	accountv1.RegisterAccountServiceServer(rpcServer, rpcHandler)
	healthv1.RegisterHealthServer(rpcServer, rpcHandler)
	rpcListener, e := net.Listen("tcp", cfg.RPCListen)
	if e != nil {
		return errors.New("RPC listener unavailable")
	}
	defer rpcListener.Close()
	activities := &jobs.Activities{Service: service}
	owner := temporalworker.New(tc, jobs.Queue, temporalworker.Options{MaxConcurrentActivityExecutionSize: 16, WorkerStopTimeout: 20 * time.Second})
	owner.RegisterWorkflow(jobs.OnboardUser)
	owner.RegisterActivity(activities)
	if e = owner.Start(); e != nil {
		return errors.New("worker startup failed")
	}
	defer owner.Stop()
	app := &api.Server{Config: cfg, Service: service, Ready: func(ctx context.Context) error {
		if err := db.Ping(ctx); err != nil {
			return err
		}
		return graphReady(ctx)
	}}
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
	stopCtx, stop := context.WithTimeout(context.Background(), 30*time.Second)
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
