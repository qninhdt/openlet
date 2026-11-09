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
	migrations, err := filepath.Glob(filepath.Join(filepath.Dir(baseline), "*.sql"))
	require.NoError(t, err)
	require.Contains(t, migrations, baseline)
	files := make([]testcontainers.ContainerFile, 0, len(migrations))
	for _, migration := range migrations {
		files = append(files, testcontainers.ContainerFile{HostFilePath: migration, ContainerFilePath: "/docker-entrypoint-initdb.d/" + filepath.Base(migration), FileMode: 0o444})
	}
	container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{
		ContainerRequest: testcontainers.ContainerRequest{
			Image:        "postgres:18.6-trixie@sha256:e3d24f6906d0760bf4da0dae872415391ededefad23fd471c47dc53b0ddf3c42",
			Env:          map[string]string{"POSTGRES_USER": "owner", "POSTGRES_DB": "application", "POSTGRES_PASSWORD": "isolated-test-password"},
			ExposedPorts: []string{"5432/tcp"},
			Files:        files,
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
