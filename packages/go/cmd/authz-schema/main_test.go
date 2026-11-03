package main

import (
	"os"
	"path/filepath"
	"testing"

	"openlet/packages/go/authz"

	"github.com/stretchr/testify/require"
)

func TestRejectsInvalidConfigurationBeforeConnecting(t *testing.T) {
	schema := filepath.Join(t.TempDir(), "schema.zed")
	require.NoError(t, os.WriteFile(schema, []byte("definition user {}"), 0600))
	t.Setenv("ALLOW_PLAINTEXT_RPC_FILE", "")
	t.Setenv("ALLOW_PLAINTEXT_RPC", "invalid")
	require.EqualError(t, run(t.Context(), schema, "../../../contracts/authz/roles.json", false), "ALLOW_PLAINTEXT_RPC must be true or false")
	t.Setenv("ALLOW_PLAINTEXT_RPC", "false")
	require.EqualError(t, run(t.Context(), schema+".missing", "../../../contracts/authz/roles.json", false), "expected authorization schema file is unavailable")
	require.EqualError(t, run(t.Context(), schema, schema+".missing", false), "expected authorization role policy file is unavailable")
	require.ErrorIs(t, run(t.Context(), schema, schema, false), authz.ErrInvalidPolicy)
	t.Setenv("SPICEDB_ADDRESS_FILE", "")
	t.Setenv("SPICEDB_ADDRESS", "invalid")
	require.EqualError(t, run(t.Context(), schema, "../../../contracts/authz/roles.json", false), "authorization transport configuration rejected")
}
