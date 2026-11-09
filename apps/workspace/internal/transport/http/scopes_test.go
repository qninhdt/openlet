package http

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/config"
	"github.com/stretchr/testify/require"
)

func TestAccessibleScopeQueryRejectsAmbiguousAuthorityBeforeService(t *testing.T) {
	secret := strings.Repeat("g", 32)
	router := (&Server{Config: config.Config{GatewayToken: secret}}).Router()
	for _, query := range []string{"user_id=" + uuid.NewString(), "leta_id=", "leta_id=invalid", "leta_id=" + uuid.Nil.String(), "limit=0", "limit=101", "limit=invalid", "limit=1&limit=2", "leta_id=" + uuid.NewString() + "&leta_id=" + uuid.NewString()} {
		request := httptest.NewRequest(http.MethodGet, "/v1/workspaces/"+uuid.NewString()+"/scopes?"+query, nil)
		request.Header.Set("X-Gateway-Token", secret)
		request.Header.Set("X-Clerk-Sub", "scope-test")
		request.Header.Set("X-Openlet-User-ID", uuid.NewString())
		response := httptest.NewRecorder()
		router.ServeHTTP(response, request)
		require.Equal(t, 400, response.Code, query+": "+response.Body.String())
		require.Contains(t, response.Body.String(), "VALIDATION")
	}
}

func TestScopeAccessRejectsInvalidGranteeKindBeforeService(t *testing.T) {
	secret := strings.Repeat("g", 32)
	router := (&Server{Config: config.Config{GatewayToken: secret}}).Router()
	for _, method := range []string{http.MethodPut, http.MethodDelete} {
		request := httptest.NewRequest(method, "/v1/workspaces/"+uuid.NewString()+"/scopes/"+uuid.NewString()+"/access/"+uuid.NewString(), strings.NewReader(`{"role":"viewer","grantee_kind":"leti"}`))
		request.Header.Set("X-Gateway-Token", secret)
		request.Header.Set("X-Clerk-Sub", "scope-test")
		request.Header.Set("X-Openlet-User-ID", uuid.NewString())
		response := httptest.NewRecorder()
		router.ServeHTTP(response, request)
		require.Equal(t, 400, response.Code, response.Body.String())
	}
}
