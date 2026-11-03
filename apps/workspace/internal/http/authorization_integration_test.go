//go:build integration

package http

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/config"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationWorkspaceListScansDeniedCandidates(t *testing.T) {
	ctx := t.Context()
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, server := testfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	data, err := os.ReadFile("../../../../packages/contracts/authz/roles.json")
	require.NoError(t, err)
	policy, err := authz.ParseRolePolicy(data)
	require.NoError(t, err)
	require.NoError(t, authz.InitializeRolePolicy(ctx, graph, policy))
	store := &workspace.Store{DB: db, Graph: graph, MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	actor := uuid.New()
	var ids []uuid.UUID
	for range 3 {
		admitted, err := store.EnsureWorkspace(ctx, workspace.CreateInput{ActorID: actor, Key: uuid.New(), Name: "Page"})
		require.NoError(t, err)
		id := admitted.ID
		require.NoError(t, store.Activate(ctx, workspace.Storage{WorkspaceID: id, BucketID: uuid.New(), FilesystemID: uuid.New(), RootID: uuid.New(), LimitBytes: "1024"}))
		ids = append(ids, id)
	}
	for _, id := range []uuid.UUID{ids[0], ids[2]} {
		require.NoError(t, store.SyncRelationships(ctx, graph, id))
	}
	secret := strings.Repeat("g", 32)
	app := &Server{Store: store, DB: db, Config: config.Config{GatewayToken: secret, WorkspaceToken: strings.Repeat("w", 32)}}
	router := app.Router()
	get := func(path string) *httptest.ResponseRecorder {
		t.Helper()
		request := httptest.NewRequest(http.MethodGet, path, nil)
		request.Header.Set("X-Gateway-Token", secret)
		request.Header.Set("X-Clerk-Sub", "list-test")
		request.Header.Set("X-Openlet-User-ID", actor.String())
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
		update := func(revision string) *httptest.ResponseRecorder {
			request := httptest.NewRequest(http.MethodPatch, path, strings.NewReader(`{"name":"Renamed"}`))
			request.Header.Set("X-Gateway-Token", secret)
			request.Header.Set("X-Clerk-Sub", "list-test")
			request.Header.Set("X-Openlet-User-ID", actor.String())
			request.Header.Set("If-Match", revision)
			response := httptest.NewRecorder()
			router.ServeHTTP(response, request)
			return response
		}
		renamed := update(before.Header().Get("ETag"))
		require.Equal(t, http.StatusOK, renamed.Code, renamed.Body.String())
		require.NotEqual(t, before.Header().Get("ETag"), renamed.Header().Get("ETag"))
		var value workspace.Workspace
		require.NoError(t, json.Unmarshal(renamed.Body.Bytes(), &value))
		require.Equal(t, "Renamed", value.Name)
		require.Equal(t, http.StatusPreconditionFailed, update(before.Header().Get("ETag")).Code)
		require.Equal(t, http.StatusOK, get(path).Code)
		require.Equal(t, http.StatusOK, update(renamed.Header().Get("ETag")).Code)
	})
	require.NoError(t, server.Stop(ctx, nil))
	require.Equal(t, http.StatusServiceUnavailable, get("/v1/workspaces").Code)
}
