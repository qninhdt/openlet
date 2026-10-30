package main

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.temporal.io/sdk/client"
	temporalworker "go.temporal.io/sdk/worker"
	"log/slog"
	"net/http"
	"openlet/services/workspace/internal/config"
	api "openlet/services/workspace/internal/http"
	"openlet/services/workspace/internal/letfs"
	worker "openlet/services/workspace/internal/temporal"
	"openlet/services/workspace/internal/user"
	"openlet/services/workspace/internal/workspace"
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
	tc, e := client.DialContext(startupCtx, client.Options{HostPort: cfg.TemporalAddress, Namespace: cfg.TemporalNamespace, Logger: slog.Default()})
	if e != nil {
		return errors.New("Temporal unavailable")
	}
	defer tc.Close()
	store := &workspace.Store{DB: db, MaxWorkspaces: cfg.MaxWorkspaces, MaxMembers: cfg.MaxMembers, QuotaLimit: cfg.QuotaLimit, InviteTTL: cfg.InviteTTL}
	storage := &letfs.Client{BaseURL: cfg.LetfsURL, Token: cfg.WorkspaceToken}
	activities := &worker.Activities{Store: store, Letfs: storage}
	owner := temporalworker.New(tc, worker.Queue, temporalworker.Options{MaxConcurrentActivityExecutionSize: 16, WorkerStopTimeout: 20 * time.Second})
	owner.RegisterWorkflow(worker.CreateWorkspace)
	owner.RegisterWorkflow(worker.DeleteWorkspace)
	owner.RegisterActivity(activities)
	if e = owner.Start(); e != nil {
		return errors.New("worker startup failed")
	}
	defer owner.Stop()
	app := &api.Server{Config: cfg, DB: db, Temporal: tc, Store: store, User: user.Client{BaseURL: cfg.UserURL, Token: cfg.WorkspaceToken}}
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
