//go:build integration

package http

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/account/internal/account"
	"github.com/qninhdt/openlet/apps/account/internal/config"
	"github.com/qninhdt/openlet/apps/account/internal/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationProfileUsesVerifiedHumanIdentity(t *testing.T) {
	store := &account.Store{DB: testfixture.Postgres(t)}
	ctx := t.Context()
	id, err := store.EnsureUser(ctx, "profile-test")
	require.NoError(t, err)
	other, err := store.EnsureUser(ctx, "other-profile")
	require.NoError(t, err)
	otherName := "Other human"
	_, err = store.UpdateProfile(ctx, other, &otherName, nil)
	require.NoError(t, err)
	secret := strings.Repeat("g", 32)
	app := &Server{
		Service: &account.Service{Store: store},
		Ready:   func(context.Context) error { return nil },
		Config:  config.Config{GatewayToken: secret},
	}
	router := app.Router()
	request := func(actor uuid.UUID, method, path, body string) *httptest.ResponseRecorder {
		t.Helper()
		r := httptest.NewRequest(method, path, strings.NewReader(body))
		r.Header.Set("X-Gateway-Token", secret)
		r.Header.Set("X-Clerk-Sub", "profile-test")
		r.Header.Set("X-Openlet-User-ID", actor.String())
		response := httptest.NewRecorder()
		router.ServeHTTP(response, r)
		return response
	}
	for _, method := range []string{http.MethodGet, http.MethodPatch} {
		response := request(uuid.New(), method, "/v1/me", `{"display_name":"unknown"}`)
		require.Equal(t, http.StatusNotFound, response.Code, response.Body.String())
	}
	response := request(id, http.MethodPatch, "/v1/me", `{"display_name":"Self"}`)
	require.Equal(t, http.StatusOK, response.Code, response.Body.String())
	response = request(id, http.MethodGet, "/v1/me", "")
	require.Equal(t, http.StatusOK, response.Code)
	var profile map[string]any
	require.NoError(t, json.Unmarshal(response.Body.Bytes(), &profile))
	require.Equal(t, id.String(), profile["id"])
	require.Equal(t, "Self", profile["display_name"])
	require.NotContains(t, profile, "type")
	require.NotContains(t, profile, "owner_id")
	for _, method := range []string{http.MethodGet, http.MethodPatch} {
		response := request(id, method, "/v1/accounts/"+other.String(), `{"display_name":"Forbidden"}`)
		require.Equal(t, http.StatusNotFound, response.Code)
	}
	require.Equal(t, http.StatusNotFound, request(id, http.MethodPost, "/v1/accounts", `{}`).Code)
	unchanged, err := store.Profile(ctx, other)
	require.NoError(t, err)
	require.Equal(t, otherName, unchanged.DisplayName)
}
