package httpapi

import (
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/stretchr/testify/require"
)

func TestHTTPAuthenticatesBeforeDispatchAndHidesPrivateRoutes(t *testing.T) {
	app := (&Server{GatewayToken: strings.Repeat("g", 32)}).Handler()
	actor := uuid.New()
	for _, test := range []struct {
		path, token string
		status      int
	}{
		{"/v1/filesystems/not-a-uuid/scopes/not-a-uuid/nodes/not-a-uuid", "", 401},
		{"/v1/filesystems/not-a-uuid/scopes/not-a-uuid/nodes/not-a-uuid", strings.Repeat("g", 32), 400},
		{"/openlet_api.letfs.v1.IngestService/PrepareParse", strings.Repeat("g", 32), 404},
		{"/internal/v1/filesystems/not-a-uuid/scopes/not-a-uuid/nodes", strings.Repeat("g", 32), 404},
	} {
		request := httptest.NewRequest("GET", test.path, nil)
		request.Header.Set("X-Gateway-Token", test.token)
		request.Header.Set("X-Openlet-Account-ID", actor.String())
		request.Header.Set("X-Clerk-Sub", "user_test")
		response := httptest.NewRecorder()
		app.ServeHTTP(response, request)
		require.Equal(t, test.status, response.Code, response.Body.String())
	}
}

func TestEmptyListAndZeroCountersRetainHTTPShapes(t *testing.T) {
	response := httptest.NewRecorder()
	request := httptest.NewRequest("GET", "/", nil)
	writeJSON(response, request, 200, "", "", struct {
		Items []nodeResponse `json:"items"`
	}{Items: []nodeResponse{}})
	require.JSONEq(t, `{"items":[]}`, response.Body.String())
}

func TestQueryLocatorPreservesExpectedIdentity(t *testing.T) {
	node, expected, parent := uuid.New(), uuid.New(), uuid.New()
	for _, target := range []string{"path=%2Fdrive%2Freport.txt", "node_id=" + node.String()} {
		request := httptest.NewRequest("GET", "/?"+target+"&expected_node_id="+expected.String()+"&expected_parent_id="+parent.String(), nil)
		locator, err := queryLocator(request)
		require.NoError(t, err)
		require.Equal(t, expected, *locator.ExpectedNodeID)
		require.Equal(t, parent, *locator.ExpectedParentID)
	}
	_, err := queryLocator(httptest.NewRequest("GET", "/?path=x&expected_node_id="+expected.String()+"&expected_node_id="+expected.String(), nil))
	require.Error(t, err)
}

func TestSearchKeepsFlatNodeIdentity(t *testing.T) {
	file := uuid.New()
	response := httptest.NewRecorder()
	err := writeSearch(response, httptest.NewRequest("GET", "/", nil), filesystem.SearchPage{Items: []filesystem.SearchResult{{Node: filesystem.Node{ID: file, Name: "report.txt"}, Path: "/report.txt"}}})
	require.NoError(t, err)
	require.JSONEq(t, `{"items":[{"node_id":"`+file.String()+`","name":"report.txt","path":"/report.txt"}],"next_cursor":null,"degraded":false}`, response.Body.String())
}

func TestSearchPreservesFullMetadataJSON(t *testing.T) {
	empty, cursor, reason := "", "next", "rerank unavailable"
	file, fs, parent, evidence, source := uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New()
	created := time.Date(2026, 1, 2, 3, 4, 5, 120000000, time.UTC)
	updated := time.Date(2026, 1, 2, 3, 4, 6, 123456789, time.UTC)
	response := httptest.NewRecorder()
	err := writeSearch(response, httptest.NewRequest("GET", "/", nil), filesystem.SearchPage{Items: []filesystem.SearchResult{{Node: filesystem.Node{ID: file, ScopeID: fs, ParentID: &parent, Name: "report.txt", Kind: "file", Revision: 9223372036854775807, SizeBytes: 9007199254740993, MediaType: &empty, Title: &empty, Description: &empty, SemanticType: &empty, Context: &empty, CreatedAt: created, UpdatedAt: updated}, Path: "/report.txt", Matched: &filesystem.SearchMatch{FileID: evidence, Snippet: "exact text", Breadcrumb: []filesystem.Breadcrumb{{NodeID: source, Filename: "source.pdf"}}}}}, NextCursor: &cursor, Degraded: true, DegradedReason: &reason})
	require.NoError(t, err)
	require.Contains(t, response.Body.String(), `"revision":"9223372036854775807"`)
	require.Contains(t, response.Body.String(), `"created_at":"2026-01-02T03:04:05.120Z"`)
	require.Contains(t, response.Body.String(), `"degraded_reason":"rerank unavailable"`)
	response = httptest.NewRecorder()
	require.NoError(t, writeSearch(response, httptest.NewRequest("GET", "/", nil), filesystem.SearchPage{}))
	require.JSONEq(t, `{"items":[],"next_cursor":null,"degraded":false}`, response.Body.String())
	response = httptest.NewRecorder()
	err = writeSearch(response, httptest.NewRequest("GET", "/", nil), filesystem.SearchPage{Items: []filesystem.SearchResult{{Node: filesystem.Node{ID: file, CreatedAt: time.Date(10000, 1, 1, 0, 0, 0, 0, time.UTC)}}}})
	require.Error(t, err)
	require.Empty(t, response.Body.String())
}

func TestSemanticSearchRejectsPaginationAndOmitsContinuation(t *testing.T) {
	for _, field := range []string{`"cursor":"next"`, `"cursor":null`, `"sort":"name"`} {
		request := httptest.NewRequest("POST", "/", strings.NewReader(`{"query":"report",`+field+`}`))
		require.Error(t, (&Server{}).semanticSearch(httptest.NewRecorder(), request))
	}
	response := httptest.NewRecorder()
	require.NoError(t, writeSearchJSON(response, searchResponse{Items: searchRows(nil)}))
	require.JSONEq(t, `{"items":[],"degraded":false}`, response.Body.String())
}
