package http

import (
	"github.com/gin-gonic/gin"
	"net/http/httptest"
	"openlet/apps/account/internal/config"
	"strings"
	"testing"
)

func TestTrustedIdentityBoundary(t *testing.T) {
	secret := strings.Repeat("x", 43)
	s := Server{Config: config.Config{GatewayToken: secret}}
	h := gin.New()
	h.Use(s.Gateway)
	h.GET("/v1/me", func(c *gin.Context) { c.Status(204) })
	h.GET("/v1/me/onboarding", func(c *gin.Context) { c.Status(204) })
	for _, c := range []struct {
		name, path, token, id, sub string
		want                       int
	}{
		{"direct-spoof", "/v1/me", "", "019ad06b-7d00-7000-8000-000000000001", "user_test", 401},
		{"missing-internal", "/v1/me", secret, "", "user_test", 401},
		{"nil-id", "/v1/me", secret, "00000000-0000-0000-0000-000000000000", "user_test", 401},
		{"bootstrap", "/v1/me/onboarding", secret, "", "user_test", 204},
		{"missing-sub", "/v1/me/onboarding", secret, "", "", 401},
		{"valid", "/v1/me", secret, "019ad06b-7d00-7000-8000-000000000001", "user_test", 204},
	} {
		t.Run(c.name, func(t *testing.T) {
			r := httptest.NewRequest("GET", c.path, nil)
			r.Header.Set("X-Gateway-Token", c.token)
			r.Header.Set("X-Openlet-User-ID", c.id)
			r.Header.Set("X-Clerk-Sub", c.sub)
			w := httptest.NewRecorder()
			h.ServeHTTP(w, r)
			if w.Code != c.want {
				t.Fatalf("got %d want %d", w.Code, c.want)
			}
		})
	}
}

func TestRouterUnknownPathsStillAuthenticate(t *testing.T) {
	s := Server{Config: config.Config{GatewayToken: strings.Repeat("x", 43)}}
	for _, path := range []string{"/v1/me", "/v1/unknown", "/v1/me/onboarding"} {
		r := httptest.NewRequest("GET", path, nil)
		w := httptest.NewRecorder()
		s.Router().ServeHTTP(w, r)
		if w.Code != 401 {
			t.Fatalf("%s bypassed authentication: %d", path, w.Code)
		}
	}
}
