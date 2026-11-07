package authz

import (
	"github.com/stretchr/testify/require"
	"os"
	"path/filepath"
	"testing"
)

func TestLoadContractRequiresNonemptySchema(t *testing.T) {
	schema := filepath.Join(t.TempDir(), "schema.zed")
	_, err := LoadContract(schema)
	require.Error(t, err)
	require.NoError(t, os.WriteFile(schema, []byte(" "), 0600))
	_, err = LoadContract(schema)
	require.Error(t, err)
	require.NoError(t, os.WriteFile(schema, []byte("definition account {}"), 0600))
	_, err = LoadContract(schema)
	require.NoError(t, err)
}
