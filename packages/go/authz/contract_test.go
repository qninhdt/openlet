package authz

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestLoadContractRejectsUnavailableOrInvalidPolicy(t *testing.T) {
	schema := filepath.Join(t.TempDir(), "schema.zed")
	roles := filepath.Join(t.TempDir(), "roles.json")
	_, err := LoadContract(schema, roles)
	require.Error(t, err)
	require.NoError(t, os.WriteFile(schema, []byte(" \n"), 0600))
	_, err = LoadContract(schema, roles)
	require.Error(t, err)
	require.NoError(t, os.WriteFile(schema, []byte("definition user {}"), 0600))
	_, err = LoadContract(schema, roles)
	require.Error(t, err)
	require.NoError(t, os.WriteFile(roles, []byte(`{"owner":["made_up"]}`), 0600))
	_, err = LoadContract(schema, roles)
	require.ErrorIs(t, err, ErrInvalidPolicy)
}
