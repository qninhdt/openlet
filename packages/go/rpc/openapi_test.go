package rpc

import (
	"encoding/json"
	"os"
	"testing"

	"github.com/pb33f/libopenapi"
	"github.com/stretchr/testify/require"
)

func TestGeneratedOpenAPIHasOnlyImplementedHTTPMappings(t *testing.T) {
	data, err := os.ReadFile("../../contracts/generated/letfs.openapi.json")
	require.NoError(t, err)
	document, err := libopenapi.NewDocument(data)
	require.NoError(t, err)
	model, problems := document.BuildV3Model()
	require.Empty(t, problems)
	require.Equal(t, "3.1.0", model.Model.Version)
	require.Equal(t, "letfs HTTP transport", model.Model.Info.Title)
	var decoded struct {
		Paths map[string]json.RawMessage `json:"paths"`
	}
	require.NoError(t, json.Unmarshal(data, &decoded))
	require.Len(t, decoded.Paths, 1, "native gRPC/admin methods cannot become imaginary HTTP routes")
	require.Contains(t, decoded.Paths, "/v1/filesystems/{filesystem_id}/nodes/{node_id}")
}
