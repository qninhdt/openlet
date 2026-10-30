// Package testinfra owns disposable dependencies shared by Go service tests.
package testinfra

import (
	"context"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
)

// Postgres creates a fresh database, then runs the production backup/migration script.
func Postgres(t *testing.T, service, migrations string) *pgxpool.Pool {
	t.Helper()
	if service != "user" && service != "workspace" {
		t.Fatal("unsupported database owner")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()
	password := "isolated-testcontainers-password"
	files, err := filepath.Glob(filepath.Join(migrations, "*.sql"))
	if err != nil || len(files) == 0 {
		t.Fatal("no service migrations found", err)
	}
	script, err := filepath.Abs("../../../../scripts/migrate.sh")
	if err != nil {
		t.Fatal(err)
	}
	copies := []testcontainers.ContainerFile{
		{HostFilePath: script, ContainerFilePath: "/migrate.sh", FileMode: 0o555},
		{Reader: strings.NewReader(password), ContainerFilePath: "/run/secrets/" + service + "_db_password", FileMode: 0o400},
	}
	for _, file := range files {
		path, err := filepath.Abs(file)
		if err != nil {
			t.Fatal(err)
		}
		copies = append(copies, testcontainers.ContainerFile{
			HostFilePath:      path,
			ContainerFilePath: "/migrations/" + service + "/migrations/" + filepath.Base(file),
			FileMode:          0o444,
		})
	}
	container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{
		ContainerRequest: testcontainers.ContainerRequest{
			Image: "postgres:18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336",
			Env: map[string]string{
				"POSTGRES_USER":     "openlet_" + service,
				"POSTGRES_DB":       "openlet_" + service,
				"POSTGRES_PASSWORD": password,
			},
			ExposedPorts: []string{"5432/tcp"}, Files: copies,
			WaitingFor: wait.ForLog("database system is ready to accept connections").
				WithOccurrence(2).
				WithStartupTimeout(time.Minute),
		}, Started: true,
	})
	if container != nil {
		testcontainers.CleanupContainer(t, container)
	}
	if err != nil {
		t.Fatal("start test PostgreSQL:", err)
	}
	code, _, err := container.Exec(ctx, []string{"sh", "/migrate.sh", service})
	if err != nil || code != 0 {
		t.Fatalf("backup/migration failed: exit=%d error=%v", code, err)
	}
	host, err := container.Host(ctx)
	if err != nil {
		t.Fatal(err)
	}
	port, err := container.MappedPort(ctx, "5432/tcp")
	if err != nil {
		t.Fatal(err)
	}
	pool, err := pgxpool.New(
		ctx,
		"postgres://openlet_"+service+":"+password+"@"+host+":"+port.Port()+"/openlet_"+service+"?sslmode=disable",
	)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	if err = pool.Ping(ctx); err != nil {
		t.Fatal(err)
	}
	return pool
}
