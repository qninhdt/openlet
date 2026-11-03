//go:build integration

package http

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/account/internal/config"
	"github.com/qninhdt/openlet/apps/account/internal/testfixture"
	"github.com/qninhdt/openlet/apps/account/internal/user"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationProfileRequiresNativeSelfPermission(t *testing.T) {
	db := testfixture.Postgres(t)
	store := &user.Store{DB: db}
	graph, _, server := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	ctx := t.Context()
	account, err := store.EnsureUser(ctx, "profile-test")
	require.NoError(t, err)
	require.NoError(t, store.Complete(ctx, "profile-test", uuid.New()))
	secret := strings.Repeat("g", 32)
	app := &Server{Store: store, DB: db, Graph: graph, Config: config.Config{GatewayToken: secret}}
	router := app.Router()
	actorID := account.UserID
	request := func(method, path, body string) *httptest.ResponseRecorder {
		t.Helper()
		r := httptest.NewRequest(method, path, strings.NewReader(body))
		r.Header.Set("X-Gateway-Token", secret)
		r.Header.Set("X-Clerk-Sub", "profile-test")
		r.Header.Set("X-Openlet-User-ID", actorID.String())
		deadline, cancel := context.WithTimeout(ctx, 3*time.Second)
		defer cancel()
		response := httptest.NewRecorder()
		router.ServeHTTP(response, r.WithContext(deadline))
		return response
	}
	actorID = uuid.New()
	for _, method := range []string{http.MethodGet, http.MethodPatch} {
		require.Equal(t, http.StatusNotFound, request(method, "/v1/me", `{"display_name":"unknown"}`).Code)
	}
	actorID = account.UserID
	for _, method := range []string{http.MethodGet, http.MethodPatch} {
		response := request(method, "/v1/me", `{"display_name":"denied"}`)
		require.Equal(t, http.StatusForbidden, response.Code, response.Body.String())
	}
	profile, err := store.Profile(ctx, account.UserID)
	require.NoError(t, err)
	require.Empty(t, profile.DisplayName)
	require.NoError(t, store.SyncRelationships(ctx, graph, account.UserID))
	require.Equal(t, http.StatusOK, request(http.MethodGet, "/v1/me", "").Code)
	require.Equal(t, http.StatusOK, request(http.MethodPatch, "/v1/me", `{"display_name":"allowed"}`).Code)
	_, err = graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "account"}})
	require.NoError(t, err)
	require.Equal(t, http.StatusForbidden, request(http.MethodPatch, "/v1/me", `{"display_name":"revoked"}`).Code)
	// Bootstrap still uses verified subject authority when no graph relationship exists.
	require.Equal(t, http.StatusOK, request(http.MethodGet, "/v1/me/onboarding", "").Code)
	require.NoError(t, server.Stop(ctx, nil))
	for _, method := range []string{http.MethodGet, http.MethodPatch} {
		require.Equal(t, http.StatusServiceUnavailable, request(method, "/v1/me", `{"display_name":"outage"}`).Code)
	}
	profile, err = store.Profile(ctx, account.UserID)
	require.NoError(t, err)
	require.Equal(t, "allowed", profile.DisplayName)
}
