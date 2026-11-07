//go:build integration

package http

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/config"
	localfixture "github.com/qninhdt/openlet/apps/workspace/internal/testfixture"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationWorkspaceListScansDeniedCandidates(t *testing.T) {
	ctx := t.Context()
	db := testfixture.Postgres(t, localfixture.Path("apps", "workspace", "migrations", "0001_initial.sql"))
	graph, _, server := testfixture.SpiceDB(t, localfixture.Path("packages", "contracts", "authz", "schema.zed"))
	store := &workspace.Store{DB: db, Graph: graph, MaxMembers: 10, InviteTTL: time.Hour}
	service := &workspace.Service{Store: store}
	actor := uuid.New()
	var ids []uuid.UUID
	for range 3 {
		id := uuid.Must(uuid.NewV7())
		_, err := service.SaveWorkspace(ctx, workspace.Creation{Input: workspace.CreateInput{ActorID: actor, Key: uuid.New(), Name: "Page"}, ID: id, FilesystemID: uuid.New(), SharedScopeID: uuid.New(), PersonalScopeID: uuid.New()})
		require.NoError(t, err)
		ids = append(ids, id)
	}
	_, err := graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: ids[1].String()}})
	require.NoError(t, err)
	secret := strings.Repeat("g", 32)
	app := &Server{Service: &workspace.Service{Store: store}, Ready: func(context.Context) error { return nil }, Config: config.Config{GatewayToken: secret, WorkspaceToken: strings.Repeat("w", 32)}}
	router := app.Router()
	get := func(path string) *httptest.ResponseRecorder {
		t.Helper()
		request := httptest.NewRequest(http.MethodGet, path, nil)
		request.Header.Set("X-Gateway-Token", secret)
		request.Header.Set("X-Clerk-Sub", "list-test")
		request.Header.Set("X-Openlet-Account-ID", actor.String())
		response := httptest.NewRecorder()
		router.ServeHTTP(response, request)
		return response
	}
	type page struct {
		Items []workspace.Workspace `json:"items"`
		Next  *string               `json:"next_cursor"`
	}
	path := "/v1/workspaces?limit=1"
	var cursors []string
	for i := range 4 {
		response := get(path)
		require.Equal(t, http.StatusOK, response.Code, response.Body.String())
		var result page
		require.NoError(t, json.Unmarshal(response.Body.Bytes(), &result))
		if i == 0 || i == 2 {
			require.Len(t, result.Items, 1)
			require.Equal(t, ids[i], result.Items[0].ID)
		} else {
			require.Empty(t, result.Items)
		}
		if i == 3 {
			require.Nil(t, result.Next)
		} else {
			require.NotNil(t, result.Next, "an empty filtered page must still advance")
			require.NotContains(t, cursors, *result.Next)
			cursors = append(cursors, *result.Next)
			path = "/v1/workspaces?limit=1&cursor=" + *result.Next
		}
	}
	require.Equal(t, http.StatusForbidden, get("/v1/workspaces/"+ids[1].String()).Code)

	t.Run("name update requires no Temporal and preserves access", func(t *testing.T) {
		path := "/v1/workspaces/" + ids[0].String()
		before := get(path)
		require.Equal(t, http.StatusOK, before.Code)
		update := func() *httptest.ResponseRecorder {
			request := httptest.NewRequest(http.MethodPatch, path, strings.NewReader(`{"name":"Renamed"}`))
			request.Header.Set("X-Gateway-Token", secret)
			request.Header.Set("X-Clerk-Sub", "list-test")
			request.Header.Set("X-Openlet-Account-ID", actor.String())
			response := httptest.NewRecorder()
			router.ServeHTTP(response, request)
			return response
		}
		renamed := update()
		require.Equal(t, http.StatusOK, renamed.Code, renamed.Body.String())
		require.Empty(t, renamed.Header().Get("ETag"))
		var value workspace.Workspace
		require.NoError(t, json.Unmarshal(renamed.Body.Bytes(), &value))
		require.Equal(t, "Renamed", value.Name)
		require.Equal(t, http.StatusOK, get(path).Code)
		require.Equal(t, http.StatusOK, update().Code)
	})
	require.NoError(t, server.Stop(ctx, nil))
	require.Equal(t, http.StatusServiceUnavailable, get("/v1/workspaces").Code)
}
