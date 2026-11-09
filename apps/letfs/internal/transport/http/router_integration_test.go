//go:build integration

package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationDirectHTTPUsesFilesystemActionsAndExactBytes(t *testing.T) {
	db := testfixture.Postgres(t, "../../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../../packages/contracts/authz/schema.zed")
	store := &filesystem.Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 1024, MaxFileBytes: 1024}
	service := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	filesystemID, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := store.CreateFilesystem(service, uuid.New(), filesystem.CreateFilesystem{ID: filesystemID, LimitBytes: 1024})
	require.NoError(t, err)
	created, err := createTestScope(service, store, uuid.New(), filesystemID, fs)
	require.NoError(t, err)
	actor, foreign := uuid.New(), uuid.New()
	testfixture.Grant(t, graph, "scope", fs, actor, authz.ScopeWrite, authz.ScopeReadMetadata, authz.ScopeReadMetadata, authz.ScopeReadContent, authz.ScopeTrash, authz.ScopeReadMetadata)
	token := strings.Repeat("g", 32)
	server := httptest.NewServer((&Server{Store: store, Service: &filesystem.Service{Store: store}, GatewayToken: token}).Handler())
	t.Cleanup(server.Close)
	request := func(method, path string, who uuid.UUID, body []byte, headers map[string]string) (*http.Response, []byte) {
		t.Helper()
		r, err := http.NewRequestWithContext(t.Context(), method, server.URL+path, bytes.NewReader(body))
		require.NoError(t, err)
		r.Header.Set("X-Gateway-Token", token)
		r.Header.Set("X-Openlet-User-ID", who.String())
		r.Header.Set("X-Clerk-Sub", "user_test")
		for key, value := range headers {
			r.Header.Set(key, value)
		}
		result, err := server.Client().Do(r)
		require.NoError(t, err)
		defer result.Body.Close()
		data, err := io.ReadAll(result.Body)
		require.NoError(t, err)
		return result, data
	}
	testfixture.Grant(t, graph, "filesystem", filesystemID, actor, authz.FilesystemRead)
	filesystemBase := "/v1/filesystems/" + filesystemID.String()
	base := filesystemBase + "/scopes/" + fs.String()
	response, data := request("GET", filesystemBase, actor, nil, nil)
	require.Equal(t, 200, response.StatusCode, string(data))
	require.NotContains(t, string(data), `"allow_blob_files"`)
	payload := []byte{0, 255, 128, 13, 10, 42}
	input, err := json.Marshal(map[string]any{"kind": "file", "parent_id": created.RootID.String(), "name": "data.bin", "content_base64": payload, "media_type": "text/html"})
	require.NoError(t, err)
	key := uuid.NewString()
	response, data = request("POST", base+"/nodes", actor, input, map[string]string{"Idempotency-Key": key})
	require.Equal(t, 201, response.StatusCode, string(data))
	location := response.Header.Get("Location")
	etag := response.Header.Get("ETag")
	repeated, again := request("POST", base+"/nodes", actor, input, map[string]string{"Idempotency-Key": key})
	require.Equal(t, 201, repeated.StatusCode)
	require.JSONEq(t, string(data), string(again))
	response, data = request("GET", location+"/content", actor, nil, map[string]string{"Range": "bytes=1-3"})
	require.Equal(t, 206, response.StatusCode, string(data))
	require.Equal(t, payload[1:4], data)
	require.Equal(t, "nosniff", response.Header.Get("X-Content-Type-Options"))
	require.Equal(t, "attachment", response.Header.Get("Content-Disposition"))
	response, data = request("GET", location, foreign, nil, nil)
	require.Contains(t, []int{403, 404}, response.StatusCode)
	require.NotContains(t, string(data), "data.bin")
	response, data = request("GET", base+"/nodes?parent_id="+created.RootID.String(), actor, nil, nil)
	require.Equal(t, 200, response.StatusCode, string(data))
	require.Contains(t, string(data), "data.bin")
	response, data = request("GET", filesystemBase, actor, nil, nil)
	require.Equal(t, 200, response.StatusCode, string(data))
	var usage struct {
		UsedBytes string `json:"used_bytes"`
	}
	require.NoError(t, json.Unmarshal(data, &usage))
	require.Equal(t, "6", usage.UsedBytes)
	restricted, err := store.CreateFilesystem(service, uuid.New(), filesystem.CreateFilesystem{ID: uuid.Must(uuid.NewV7()), LimitBytes: 1024})
	require.NoError(t, err)
	testfixture.Grant(t, graph, "filesystem", restricted.ID, actor, authz.FilesystemRead)
	scopes, err := store.CreateScopes(service, uuid.New(), restricted.ID, []uuid.UUID{uuid.Must(uuid.NewV7())}, false, true)
	require.NoError(t, err)
	scope := scopes[0]
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", scope.ID, actor, authz.ScopeWrite)
	restrictedBase := "/v1/filesystems/" + restricted.ID.String()
	response, data = request("GET", restrictedBase, actor, nil, nil)
	require.Equal(t, 200, response.StatusCode, string(data))
	require.NotContains(t, string(data), `"allow_blob_files"`)
	input, err = json.Marshal(map[string]any{"kind": "file", "parent_id": scope.RootID.String(), "name": "binary.txt", "content_base64": payload, "media_type": "text/plain"})
	require.NoError(t, err)
	response, data = request("POST", restrictedBase+"/scopes/"+scope.ID.String()+"/nodes", actor, input, map[string]string{"Idempotency-Key": uuid.NewString()})
	require.Equal(t, 400, response.StatusCode, string(data))
	require.Contains(t, string(data), "BLOB_FILES_DISABLED")
	response, data = request("DELETE", location, actor, nil, map[string]string{"If-Match": etag})
	require.Equal(t, 201, response.StatusCode, string(data))
	require.Contains(t, response.Header.Get("Location"), "/trash-entries/")
	_, err = graph.DeleteRelationships(t.Context(), &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "scope", OptionalResourceId: fs.String()}})
	require.NoError(t, err)
	response, data = request("GET", base+"/nodes?parent_id="+created.RootID.String(), actor, nil, nil)
	require.Equal(t, 403, response.StatusCode)
	require.NotContains(t, string(data), "data.bin")
}
