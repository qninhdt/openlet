package httpapi

import (
	"context"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/timestamppb"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/identity"
)

type publicProbe struct {
	letfsv1.UnimplementedFilesystemServiceServer
	actor uuid.UUID
}

func (s *publicProbe) GetNode(ctx context.Context, input *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error) {
	principal, _ := identity.FromContext(ctx)
	s.actor = principal.ActorID
	return &letfsv1.GetNodeResponse{Node: &letfsv1.Node{Id: input.NodeId, FilesystemId: input.FilesystemId, Revision: 7}}, nil
}
func TestHTTPAuthenticatesBeforeInProcessDispatchAndHidesPrivateRoutes(t *testing.T) {
	probe := &publicProbe{}
	app := (&Server{API: probe, GatewayToken: strings.Repeat("g", 32)}).Handler()
	actor := uuid.New()
	for _, test := range []struct {
		path, token string
		status      int
	}{
		{"/v1/filesystems/fs/nodes/node", "", 401},
		{"/v1/filesystems/fs/nodes/node", strings.Repeat("g", 32), 200},
		{"/openlet_api.letfs.v1.IngestService/PrepareParse", strings.Repeat("g", 32), 404},
		{"/internal/v1/filesystems/fs/nodes", strings.Repeat("g", 32), 404},
	} {
		request := httptest.NewRequest("GET", test.path, nil)
		request.Header.Set("X-Gateway-Token", test.token)
		request.Header.Set("X-Openlet-User-ID", actor.String())
		request.Header.Set("X-Clerk-Sub", "user_test")
		response := httptest.NewRecorder()
		app.ServeHTTP(response, request)
		require.Equal(t, test.status, response.Code, response.Body.String())
		if response.Code == 200 {
			require.Equal(t, actor, probe.actor)
			require.Equal(t, `"7"`, response.Header().Get("ETag"))
		}
	}
}
func TestEmptyListAndZeroCountersRetainHTTPShapes(t *testing.T) {
	response := httptest.NewRecorder()
	request := httptest.NewRequest("GET", "/", nil)
	writeProto(response, request, 200, "", "", &letfsv1.ListNodesResponse{})
	require.JSONEq(t, `{"items":[]}`, response.Body.String())
	response = httptest.NewRecorder()
	writeProto(response, request, 200, "", "", &letfsv1.Copy{Status: "accepted"})
	require.Contains(t, response.Body.String(), `"committed_nodes":"0"`)
}

func TestQueryLocatorPreservesExpectedIdentity(t *testing.T) {
	for _, target := range []string{"path=%2Fdrive%2Freport.txt", "node_id=selected"} {
		request := httptest.NewRequest("GET", "/?"+target+"&expected_node_id=expected&expected_parent_id=parent", nil)
		locator, err := queryLocator(request)
		require.NoError(t, err)
		require.Equal(t, "expected", locator.GetExpectedNodeId())
		require.Equal(t, "parent", locator.GetExpectedParentId())
	}
	_, err := queryLocator(httptest.NewRequest("GET", "/?path=x&expected_node_id=a&expected_node_id=b", nil))
	require.Error(t, err)
}

func TestMountPathDefaultsAndOverrides(t *testing.T) {
	require.Equal(t, "/", mountPath(httptest.NewRequest("GET", "/", nil)))
	require.Equal(t, "/documents", mountPath(httptest.NewRequest("GET", "/?mount_path=%2Fdocuments", nil)))
}

func TestSearchKeepsFlatNodeIdentity(t *testing.T) {
	response := httptest.NewRecorder()
	err := writeSearch(response, httptest.NewRequest("GET", "/", nil), []*letfsv1.SearchResult{
		{Node: &letfsv1.Node{Id: "file", Name: "report.txt"}, Path: "/report.txt"},
	}, nil, false, nil)
	require.NoError(t, err)
	require.JSONEq(t, `{"items":[{"node_id":"file","name":"report.txt","path":"/report.txt"}],"next_cursor":null,"degraded":false}`, response.Body.String())
}

func TestSearchPreservesFullMetadataJSON(t *testing.T) {
	empty, parent, cursor, reason := "", "parent", "next", "rerank unavailable"
	response := httptest.NewRecorder()
	err := writeSearch(response, httptest.NewRequest("GET", "/", nil), []*letfsv1.SearchResult{
		{Node: &letfsv1.Node{
			Id: "file", FilesystemId: "fs", ParentId: &parent, Name: "report.txt", Kind: "file",
			Revision: 9223372036854775807, SizeBytes: 9007199254740993,
			MediaType: &empty, Title: &empty, Description: &empty, SemanticType: &empty, Context: &empty,
			CreatedAt: timestamppb.New(time.Date(2026, 1, 2, 3, 4, 5, 120000000, time.UTC)),
			UpdatedAt: timestamppb.New(time.Date(2026, 1, 2, 3, 4, 6, 123456789, time.UTC)),
		}, Path: "/report.txt", Matched: &letfsv1.SearchMatch{
			FileId: "evidence", Snippet: "exact text", Breadcrumb: []*letfsv1.Breadcrumb{{NodeId: "source", Filename: "source.pdf"}},
		}},
	}, &cursor, true, &reason)
	require.NoError(t, err)
	require.JSONEq(t, `{"items":[{
		"node_id":"file","filesystem_id":"fs","parent_id":"parent","name":"report.txt","kind":"file",
		"revision":"9223372036854775807","size_bytes":"9007199254740993",
		"media_type":"","title":"","description":"","semantic_type":"","context":"",
		"created_at":"2026-01-02T03:04:05.120Z","updated_at":"2026-01-02T03:04:06.123456789Z",
		"path":"/report.txt","matched":{"file_id":"evidence","snippet":"exact text","breadcrumb":[{"node_id":"source","filename":"source.pdf"}]}
	}],"next_cursor":"next","degraded":true,"degraded_reason":"rerank unavailable"}`, response.Body.String())

	response = httptest.NewRecorder()
	require.NoError(t, writeSearch(response, httptest.NewRequest("GET", "/", nil), nil, nil, false, nil))
	require.JSONEq(t, `{"items":[],"next_cursor":null,"degraded":false}`, response.Body.String())
	response = httptest.NewRecorder()
	err = writeSearch(response, httptest.NewRequest("GET", "/", nil), []*letfsv1.SearchResult{
		{Node: &letfsv1.Node{Id: "file", CreatedAt: &timestamppb.Timestamp{Seconds: 253402300800}}},
	}, nil, false, nil)
	require.Error(t, err)
	require.Empty(t, response.Body.String())
	require.Empty(t, response.Header().Get("Content-Type"))
}
