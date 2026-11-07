//go:build integration

package testfixture

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
	"go.temporal.io/sdk/client"
)

func Temporal(t *testing.T) (client.Client, string) {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	server, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{Started: true, ContainerRequest: testcontainers.ContainerRequest{
		Image:        "temporalio/admin-tools:1.32.1@sha256:9ef0dc5b063bf4ffd5c1512de72e0e73e225bd2c7006a18ce69bd592a8862a83",
		Entrypoint:   []string{"temporal"},
		Cmd:          []string{"server", "start-dev", "--ip", "0.0.0.0", "--headless", "--namespace", "openlet", "--port", "7233"},
		ExposedPorts: []string{"7233/tcp"},
		WaitingFor:   wait.ForListeningPort("7233/tcp").WithStartupTimeout(45 * time.Second),
	}})
	if server != nil {
		testcontainers.CleanupContainer(t, server)
	}
	require.NoError(t, err)
	host, err := server.Host(ctx)
	require.NoError(t, err)
	port, err := server.MappedPort(ctx, "7233/tcp")
	require.NoError(t, err)
	address := net.JoinHostPort(host, port.Port())
	tc, err := client.DialContext(ctx, client.Options{HostPort: address, Namespace: "openlet"})
	require.NoError(t, err)
	t.Cleanup(tc.Close)
	_, err = tc.CheckHealth(ctx, &client.CheckHealthRequest{})
	require.NoError(t, err)
	return tc, address
}
