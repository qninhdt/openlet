package main

import (
	"context"
	"errors"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/exaring/otelpgx"
	"github.com/gin-gonic/gin"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/qninhdt/openlet/apps/workspace/internal/config"
	api "github.com/qninhdt/openlet/apps/workspace/internal/http"
	worker "github.com/qninhdt/openlet/apps/workspace/internal/temporal"
	"github.com/qninhdt/openlet/apps/workspace/internal/user"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/qninhdt/openlet/packages/go/authz"
	accountv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/account/v1"
	sharedrpc "github.com/qninhdt/openlet/packages/go/rpc"
	"github.com/qninhdt/openlet/packages/go/telemetry"
	"go.opentelemetry.io/otel/propagation"
	"go.temporal.io/sdk/client"
	temporalotel "go.temporal.io/sdk/contrib/opentelemetry"
	"go.temporal.io/sdk/interceptor"
	temporalworker "go.temporal.io/sdk/worker"
	"google.golang.org/grpc"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"log/slog"
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
	store := &workspace.Store{DB: db, Graph: graph, MaxWorkspaces: cfg.MaxWorkspaces, MaxMembers: cfg.MaxMembers, QuotaLimit: cfg.QuotaLimit, InviteTTL: cfg.InviteTTL}
	if len(os.Args) == 2 && os.Args[1] == "--rebuild-authorization" {
		return store.RebuildRelationships(ctx, graph)
	}
	tracing, e := temporalotel.NewTracingInterceptor(temporalotel.TracerOptions{DisableBaggage: true, TextMapPropagator: propagation.TraceContext{}})
	if e != nil {
		return errors.New("Temporal tracing configuration rejected")
	}
	tc, e := client.DialContext(startupCtx, client.Options{HostPort: cfg.TemporalAddress, Namespace: cfg.TemporalNamespace, Logger: slog.Default(), Interceptors: []interceptor.ClientInterceptor{tracing}, MetricsHandler: temporalotel.NewMetricsHandler(temporalotel.MetricsHandlerOptions{})})
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
		return errors.New("Account RPC unavailable")
	}
	activities := &worker.Activities{Store: store, Temporal: tc, Graph: graph}
	owner := temporalworker.New(tc, worker.Queue, temporalworker.Options{MaxConcurrentActivityExecutionSize: 16, WorkerStopTimeout: 20 * time.Second})
	owner.RegisterWorkflow(worker.CreateWorkspace)
	owner.RegisterWorkflow(worker.DeleteWorkspace)
	owner.RegisterWorkflow(worker.ReconcileWorkspaces)
	owner.RegisterWorkflow(worker.SyncWorkspace)
	owner.RegisterActivity(activities)
	if e = owner.Start(); e != nil {
		return errors.New("worker startup failed")
	}
	defer owner.Stop()
	if e = worker.EnsureReconciliation(startupCtx, tc); e != nil {
		return errors.New("reconciliation schedule unavailable")
	}
	app := &api.Server{GraphReady: graphReady, Config: cfg, DB: db, Temporal: tc, Store: store, User: user.Client{API: accountv1.NewAccountServiceClient(accountConnection)}}
	srv := &http.Server{Addr: cfg.Listen, Handler: app.Router(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 125 * time.Second, WriteTimeout: 125 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 32768}
	errch := make(chan error, 1)
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
	return srv.Shutdown(stopCtx)
}
