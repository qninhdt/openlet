//go:build integration

package authz

import (
	"context"
	"os"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	authzed "github.com/authzed/authzed-go/v1"
	"github.com/authzed/grpcutil"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
)

func TestIntegrationSchemaInitializationAndReadiness(t *testing.T) {
	client, address, server := testfixture.SpiceDB(t, "")
	ctx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
	defer cancel()
	schema, err := os.ReadFile("../../contracts/authz/schema.zed")
	require.NoError(t, err)
	expected := string(schema)
	require.Equal(t, codes.NotFound, status.Code(VerifySchema(ctx, client, expected)))
	err = InitializeSchema(ctx, client, expected)
	if err != nil {
		actual, readErr := client.ReadSchema(ctx, &v1.ReadSchemaRequest{})
		require.NoError(t, readErr)
		require.Equal(t, expected, actual.SchemaText, "schema must use the pinned server's canonical format")
	}
	require.NoError(t, err)
	require.NoError(t, InitializeSchema(ctx, client, expected), "repeat initialization is read-only")
	require.NoError(t, VerifySchema(ctx, client, expected))
	unauthorized, err := authzed.NewClient(address, grpc.WithTransportCredentials(insecure.NewCredentials()), grpcutil.WithInsecureBearerToken("incorrect-graph-credential"))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, unauthorized.Close()) })
	require.Equal(t, codes.PermissionDenied, status.Code(VerifySchema(ctx, unauthorized, expected)), "SpiceDB rejects an incorrect preshared key")
	require.ErrorIs(t, InitializeSchema(ctx, client, "definition unrelated {}"), ErrSchemaMismatch)
	require.ErrorIs(t, InitializeSchema(ctx, client, ""), ErrSchemaMismatch)
	require.NoError(t, VerifySchema(ctx, client, expected), "mismatch must not alter existing policy")

	canceled, stop := context.WithCancel(ctx)
	stop()
	require.Equal(t, codes.Canceled, status.Code(VerifySchema(canceled, client, expected)))
	require.NoError(t, server.Stop(ctx, nil))
	deadline, stop := context.WithTimeout(ctx, 200*time.Millisecond)
	defer stop()
	require.Error(t, VerifySchema(deadline, client, expected), "stopped graph cannot report ready")
}

func TestIntegrationInvalidSchemaCannotInitialize(t *testing.T) {
	client, _, _ := testfixture.SpiceDB(t, "")
	ctx, cancel := context.WithTimeout(t.Context(), 30*time.Second)
	defer cancel()
	require.Error(t, InitializeSchema(ctx, client, "invalid schema"))
	_, err := client.ReadSchema(ctx, &v1.ReadSchemaRequest{})
	require.Equal(t, codes.NotFound, status.Code(err), "failed initialization must leave no schema")
}
