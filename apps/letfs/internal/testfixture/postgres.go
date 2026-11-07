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

func Postgres(t *testing.T, baseline string) *pgxpool.Pool {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	path, err := filepath.Abs(baseline)
	require.NoError(t, err)
	migrations, err := filepath.Glob(filepath.Join(filepath.Dir(path), "*.sql"))
	require.NoError(t, err)
	files := make([]testcontainers.ContainerFile, 0, len(migrations))
	for _, migration := range migrations {
		files = append(files, testcontainers.ContainerFile{HostFilePath: migration, ContainerFilePath: "/docker-entrypoint-initdb.d/" + filepath.Base(migration), FileMode: 0o444})
	}
	server, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{Started: true, ContainerRequest: testcontainers.ContainerRequest{
		Image:        "postgres:18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336",
		Env:          map[string]string{"POSTGRES_USER": "owner", "POSTGRES_DB": "application", "POSTGRES_PASSWORD": "isolated-test-password"},
		ExposedPorts: []string{"5432/tcp"},
		Files:        files,
		WaitingFor:   wait.ForLog("database system is ready to accept connections").WithOccurrence(2).WithStartupTimeout(30 * time.Second),
	}})
	if server != nil {
		testcontainers.CleanupContainer(t, server)
	}
	require.NoError(t, err)
	host, err := server.Host(ctx)
	require.NoError(t, err)
	port, err := server.MappedPort(ctx, "5432/tcp")
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
