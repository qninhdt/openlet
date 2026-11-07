package main

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestRejectsInvalidConfigurationBeforeConnecting(t *testing.T) {
	schema := filepath.Join(t.TempDir(), "schema.zed")
	require.NoError(t, os.WriteFile(schema, []byte("definition user {}"), 0600))
	t.Setenv("ALLOW_PLAINTEXT_RPC_FILE", "")
	t.Setenv("ALLOW_PLAINTEXT_RPC", "invalid")
	require.EqualError(t, run(t.Context(), schema, false), "ALLOW_PLAINTEXT_RPC must be true or false")
	t.Setenv("ALLOW_PLAINTEXT_RPC", "false")
	require.EqualError(t, run(t.Context(), schema+".missing", false), "expected authorization schema file is unavailable")
	t.Setenv("SPICEDB_ADDRESS_FILE", "")
	t.Setenv("SPICEDB_ADDRESS", "invalid")
	require.EqualError(t, run(t.Context(), schema, false), "authorization transport configuration rejected")
}
