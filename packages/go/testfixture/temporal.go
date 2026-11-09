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
		Image:        "temporalio/admin-tools:1.32.2@sha256:4a95866efba29d7e17ab012df5232795e8b0ad0f7d5f9d1ec4df321f7792a754",
		Entrypoint:   []string{"temporal"},
		Cmd:          []string{"server", "start-dev", "--ip", "0.0.0.0", "--headless", "--namespace", "openlet", "--port", "7233"},
		ExposedPorts: []string{"7233/tcp"},
		// An open TCP listener can precede gRPC and namespace initialization.
		WaitingFor: wait.ForExec([]string{"temporal", "operator", "namespace", "describe", "--namespace", "openlet", "--address", "127.0.0.1:7233"}).WithStartupTimeout(45 * time.Second),
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
