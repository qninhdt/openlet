//go:build integration

package testfixture

import (
	"context"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	authzed "github.com/authzed/authzed-go/v1"
	"github.com/authzed/grpcutil"
	"github.com/stretchr/testify/require"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/network"
	"github.com/testcontainers/testcontainers-go/wait"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"net"
	"os"
	"testing"
	"time"
)

const spiceImage = "authzed/spicedb:v1.57.0@sha256:2e0cd20aa923ccfd96eb285756ec10a5d7bbe387e4b29c26bd6447435d2328de"
const SpiceDBKey = "isolated-graph-key-for-integration-fixtures"

func SpiceDB(t *testing.T, schemaPath string) (*authzed.Client, string, testcontainers.Container) {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), 2*time.Minute)
	defer cancel()
	nw, err := network.New(ctx)
	require.NoError(t, err)
	testcontainers.CleanupNetwork(t, nw)
	start := func(request testcontainers.ContainerRequest) testcontainers.Container {
		t.Helper()
		request.Networks = []string{nw.Name}
		container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{ContainerRequest: request, Started: true})
		if container != nil {
			testcontainers.CleanupContainer(t, container)
		}
		require.NoError(t, err)
		return container
	}
	start(testcontainers.ContainerRequest{
		Image:          "postgres:18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336",
		Env:            map[string]string{"POSTGRES_USER": "graph", "POSTGRES_PASSWORD": "isolated-graph-password", "POSTGRES_DB": "graph"},
		NetworkAliases: map[string][]string{nw.Name: {"postgres"}},
		WaitingFor:     wait.ForLog("database system is ready to accept connections").WithOccurrence(2).WithStartupTimeout(time.Minute),
	})
	dsn := "postgres://graph:isolated-graph-password@postgres:5432/graph?sslmode=disable"
	migration := start(testcontainers.ContainerRequest{Image: spiceImage,
		Cmd:        []string{"datastore", "migrate", "head", "--datastore-engine=postgres", "--datastore-conn-uri=" + dsn, "--skip-release-check"},
		WaitingFor: wait.ForExit().WithExitTimeout(time.Minute),
	})
	state, err := migration.State(ctx)
	require.NoError(t, err)
	require.Equal(t, 0, state.ExitCode, "SpiceDB migrations must succeed")
	server := start(testcontainers.ContainerRequest{Image: spiceImage, ExposedPorts: []string{"50051/tcp"},
		Cmd: []string{"serve", "--datastore-engine=postgres", "--datastore-conn-uri=" + dsn, "--grpc-preshared-key=" + SpiceDBKey,
			"--grpc-tls-cert-path=", "--grpc-tls-key-path=", "--skip-release-check",
			"--datastore-conn-pool-read-min-open=1", "--datastore-conn-pool-read-max-open=4",
			"--datastore-conn-pool-write-min-open=1", "--datastore-conn-pool-write-max-open=4"},
		WaitingFor: wait.ForAll(
			wait.ForListeningPort("50051/tcp").SkipInternalCheck(),
			wait.ForExec([]string{"/usr/local/bin/grpc_health_probe", "-addr=localhost:50051", "-rpc-timeout=1s"}),
		).WithDeadline(time.Minute),
	})
	host, err := server.Host(ctx)
	require.NoError(t, err)
	port, err := server.MappedPort(ctx, "50051/tcp")
	require.NoError(t, err)
	address := net.JoinHostPort(host, port.Port())
	client := SpiceDBClient(t, address)
	if schemaPath == "" {
		return client, address, server
	}
	schema, err := os.ReadFile(schemaPath)
	require.NoError(t, err)
	_, err = client.WriteSchema(ctx, &v1.WriteSchemaRequest{Schema: string(schema)})
	require.NoError(t, err)
	return client, address, server
}

func SpiceDBClient(t *testing.T, address string) *authzed.Client {
	t.Helper()
	client, err := authzed.NewClient(address, grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithDefaultCallOptions(grpc.WaitForReady(true)), grpcutil.WithInsecureBearerToken(SpiceDBKey))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, client.Close()) })
	return client
}
