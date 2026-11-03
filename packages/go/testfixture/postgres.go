//go:build integration

package testfixture

import (
	"context"
	"net"
	"path/filepath"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/stretchr/testify/require"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
)

func Postgres(t *testing.T, migrationPath string) *pgxpool.Pool {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	baseline, err := filepath.Abs(migrationPath)
	require.NoError(t, err)
	container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{
		ContainerRequest: testcontainers.ContainerRequest{
			Image:        "postgres:18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336",
			Env:          map[string]string{"POSTGRES_USER": "owner", "POSTGRES_DB": "application", "POSTGRES_PASSWORD": "isolated-test-password"},
			ExposedPorts: []string{"5432/tcp"},
			Files:        []testcontainers.ContainerFile{{HostFilePath: baseline, ContainerFilePath: "/docker-entrypoint-initdb.d/10-baseline.sql", FileMode: 0o444}},
			WaitingFor:   wait.ForLog("database system is ready to accept connections").WithOccurrence(2).WithStartupTimeout(45 * time.Second),
		}, Started: true,
	})
	if container != nil {
		testcontainers.CleanupContainer(t, container)
	}
	require.NoError(t, err)
	host, err := container.Host(ctx)
	require.NoError(t, err)
	port, err := container.MappedPort(ctx, "5432/tcp")
	require.NoError(t, err)
	config, err := pgxpool.ParseConfig("postgres://owner:isolated-test-password@" + net.JoinHostPort(host, port.Port()) + "/application?sslmode=disable")
	require.NoError(t, err)
	config.MaxConns = 8
	config.ConnConfig.RuntimeParams["statement_timeout"] = "5000"
	config.ConnConfig.RuntimeParams["lock_timeout"] = "3000"
	db, err := pgxpool.NewWithConfig(ctx, config)
	require.NoError(t, err)
	t.Cleanup(db.Close)
	require.NoError(t, db.Ping(ctx))
	return db
}
