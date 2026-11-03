//go:build integration

package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
	"openlet/packages/go/authz"
	"openlet/packages/go/testfixture"
)

func TestIntegrationInitializerConfigurationAndFailures(t *testing.T) {
	_, address, _ := testfixture.SpiceDB(t, "")
	key := filepath.Join(t.TempDir(), "graph-key")
	require.NoError(t, os.WriteFile(key, []byte(testfixture.SpiceDBKey+"\n"), 0600))
	t.Setenv("SPICEDB_ADDRESS_FILE", "")
	t.Setenv("SPICEDB_ADDRESS", address)
	t.Setenv("SPICEDB_GRPC_PRESHARED_KEY_FILE", key)
	t.Setenv("SPICEDB_GRPC_PRESHARED_KEY", "ignored-direct-value")
	t.Setenv("ALLOW_PLAINTEXT_RPC_FILE", "")
	t.Setenv("ALLOW_PLAINTEXT_RPC", "true")
	schema := "../../../contracts/authz/schema.zed"
	roles := "../../../contracts/authz/roles.json"
	require.EqualError(t, run(t.Context(), schema, roles, true), "authorization schema operation failed (NotFound)")
	require.NoError(t, run(t.Context(), schema, roles, false))
	require.NoError(t, run(t.Context(), schema, roles, false))
	require.NoError(t, run(t.Context(), schema, roles, true))
	other := filepath.Join(t.TempDir(), "schema.zed")
	require.NoError(t, os.WriteFile(other, []byte("definition unrelated {}"), 0600))
	require.ErrorIs(t, run(t.Context(), other, roles, false), authz.ErrSchemaMismatch)
	require.NoError(t, run(t.Context(), schema, roles, true), "mismatch cannot replace installed policy")
	require.NoError(t, os.WriteFile(key, []byte(strings.Repeat("w", 32)), 0600))
	require.EqualError(t, run(t.Context(), schema, roles, true), "authorization schema operation failed (PermissionDenied)")
}
