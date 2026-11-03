//go:build integration

package testfixture

import (
	"context"
	"net"
	"net/http"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
)

const QdrantKey = "isolated-qdrant-test-token"

func Qdrant(t *testing.T) string {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	server, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{Started: true, ContainerRequest: testcontainers.ContainerRequest{
		Image: "qdrant/qdrant:v1.20.0@sha256:9bfc89f9914fc14876a88c05270685921a55b8877b254a98bcc1cc2f0a424cd2",
		Env:   map[string]string{"QDRANT__SERVICE__API_KEY": QdrantKey}, ExposedPorts: []string{"6333/tcp"},
		WaitingFor: wait.ForHTTP("/readyz").WithPort("6333/tcp").WithHeaders(map[string]string{"api-key": QdrantKey}).WithStatusCodeMatcher(func(code int) bool { return code == http.StatusOK }).WithStartupTimeout(30 * time.Second),
	}})
	if server != nil {
		testcontainers.CleanupContainer(t, server)
	}
	require.NoError(t, err)
	host, err := server.Host(ctx)
	require.NoError(t, err)
	port, err := server.MappedPort(ctx, "6333/tcp")
	require.NoError(t, err)
	return "http://" + net.JoinHostPort(host, port.Port())
}
