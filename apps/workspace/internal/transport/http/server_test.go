package http

import (
	"github.com/gin-gonic/gin"
	"github.com/qninhdt/openlet/apps/workspace/internal/config"
	"github.com/qninhdt/openlet/packages/go/identity"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/google/uuid"
)

func TestTrustedIdentityBoundary(t *testing.T) {
	secret := strings.Repeat("x", 43)
	s := Server{Config: config.Config{GatewayToken: secret}}
	h := gin.New()
	h.Use(s.Gateway)
	h.GET("/v1/me", func(c *gin.Context) {
		principal, ok := identity.FromContext(c.Request.Context())
		if !ok || !principal.Gateway || principal.ActorID == uuid.Nil || principal.Subject != "user_test" {
			t.Fatal("handler did not receive verified user identity")
		}
		c.Status(204)
	})
	h.GET("/v1/onboarding", func(c *gin.Context) { c.Status(204) })
	for _, c := range []struct {
		name, path, token, id, sub string
		want                       int
	}{
		{"direct-spoof", "/v1/me", "", "019ad06b-7d00-7000-8000-000000000001", "user_test", 401},
		{"missing-internal", "/v1/me", secret, "", "user_test", 401},
		{"nil-id", "/v1/me", secret, "00000000-0000-0000-0000-000000000000", "user_test", 401},
		{"bootstrap", "/v1/onboarding", secret, "", "user_test", 401},
		{"missing-sub", "/v1/onboarding", secret, "", "", 401},
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

func TestPaginationBoundaries(t *testing.T) {
	for _, c := range []struct {
		query string
		limit int
		valid bool
	}{
		{"", 50, true},
		{"limit=1", 1, true},
		{"limit=100", 100, true},
		{"limit=0", 0, false},
		{"limit=-1", 0, false},
		{"limit=101", 0, false},
		{"limit=abc", 0, false},
		{"limit=10&cursor=opaque-letfs-cursor", 10, true},
	} {
		t.Run(c.query, func(t *testing.T) {
			limit, err := pageLimit(httptest.NewRequest("GET", "/?"+c.query, nil))
			if (err == nil) != c.valid || limit != c.limit {
				t.Fatalf("limit=%d error=%v; want limit=%d valid=%t", limit, err, c.limit, c.valid)
			}
		})
	}
	id := uuid.MustParse("019ad06b-7d00-7000-8000-000000000001")
	r := httptest.NewRequest("GET", "/?limit=1&cursor="+*cursor("members/workspace", id), nil)
	after, limit, err := page(r, "members/workspace")
	if err != nil || after != id || limit != 1 {
		t.Fatalf("valid scoped cursor: after=%v limit=%d error=%v", after, limit, err)
	}
	if _, _, err = page(r, "invitations/workspace"); err == nil {
		t.Fatal("accepted cursor from another collection")
	}
}

func TestRouterUnknownPathsStillAuthenticate(t *testing.T) {
	s := Server{Config: config.Config{GatewayToken: strings.Repeat("x", 43)}}
	for _, path := range []string{"/v1/me", "/v1/unknown", "/v1/onboarding", "/v1/workspaces/019ad06b-7d00-7000-8000-000000000001/files/processing-status"} {
		r := httptest.NewRequest("GET", path, nil)
		w := httptest.NewRecorder()
		s.Router().ServeHTTP(w, r)
		if w.Code != 401 {
			t.Fatalf("%s bypassed authentication: %d", path, w.Code)
		}
	}
}

func TestFileFacadeRoutesAreRemoved(t *testing.T) {
	s := Server{Config: config.Config{GatewayToken: strings.Repeat("g", 32)}}
	router := s.Router()
	for _, path := range []string{"/nodes", "/uploads", "/search", "/trash-entries", "/storage", "/nodes/node/archive"} {
		request := httptest.NewRequest("GET", "/v1/workspaces/"+uuid.NewString()+path, nil)
		request.Header.Set("X-Gateway-Token", s.Config.GatewayToken)
		request.Header.Set("X-Clerk-Sub", "user_test")
		request.Header.Set("X-Openlet-User-ID", uuid.NewString())
		response := httptest.NewRecorder()
		router.ServeHTTP(response, request)
		if response.Code != 404 {
			t.Fatalf("old facade %s remains reachable: %d", path, response.Code)
		}
	}
}
