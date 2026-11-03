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
	handlers "github.com/qninhdt/openlet/apps/letfs/internal/grpc"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationDirectHTTPUsesFilesystemActionsAndExactBytes(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	store := &filesystem.Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 1024, MaxFileBytes: 1024}
	service := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	bucket, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := store.CreateBucket(service, uuid.New(), filesystem.CreateBucket{ID: bucket, LimitBytes: 1024})
	require.NoError(t, err)
	created, err := store.CreateFilesystem(service, uuid.New(), filesystem.CreateFilesystem{ID: fs, BucketID: bucket, RootName: "files"})
	require.NoError(t, err)
	actor, foreign := uuid.New(), uuid.New()
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeCreate, authz.NodeRead, authz.NodeList, authz.ContentRead, authz.NodeTrash, authz.TrashRead)
	token := strings.Repeat("g", 32)
	server := httptest.NewServer((&Server{API: &handlers.Filesystem{Store: store}, Store: store, GatewayToken: token}).Handler())
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
	base := "/v1/filesystems/" + fs.String()
	payload := []byte{0, 255, 128, 13, 10, 42}
	input, err := json.Marshal(map[string]any{"kind": "file", "parent_id": created.RootID.String(), "name": "data.bin", "content_base64": payload, "media_type": "text/html"})
	require.NoError(t, err)
	key := uuid.NewString()
	response, data := request("POST", base+"/nodes", actor, input, map[string]string{"Idempotency-Key": key})
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
	// A filesystem grant cannot authorize the bucket-wide usage operation.
	response, _ = request("GET", "/v1/quota-buckets/"+bucket.String(), actor, nil, nil)
	require.Equal(t, 403, response.StatusCode)
	testfixture.Grant(t, graph, "quota_bucket", bucket, actor, authz.BucketRead)
	response, data = request("GET", "/v1/quota-buckets/"+bucket.String(), actor, nil, nil)
	require.Equal(t, 200, response.StatusCode, string(data))
	var usage struct {
		Bucket struct {
			UsedBytes string `json:"used_bytes"`
		} `json:"bucket"`
		UploadLimits struct {
			InlineLimitBytes string `json:"inline_limit_bytes"`
		} `json:"upload_limits"`
	}
	require.NoError(t, json.Unmarshal(data, &usage))
	require.Equal(t, "6", usage.Bucket.UsedBytes)
	require.Equal(t, "1024", usage.UploadLimits.InlineLimitBytes)
	response, data = request("DELETE", location, actor, nil, map[string]string{"If-Match": etag})
	require.Equal(t, 201, response.StatusCode, string(data))
	require.Contains(t, response.Header.Get("Location"), "/trash-entries/")
	_, err = graph.DeleteRelationships(t.Context(), &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "filesystem", OptionalResourceId: fs.String()}})
	require.NoError(t, err)
	response, data = request("GET", base+"/nodes?parent_id="+created.RootID.String(), actor, nil, nil)
	require.Equal(t, 403, response.StatusCode)
	require.NotContains(t, string(data), "data.bin")
}
