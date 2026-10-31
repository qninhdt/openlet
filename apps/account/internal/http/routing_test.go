package http

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
)

func TestGinAuthenticationAndRecovery(t *testing.T) {
	secret := strings.Repeat("x", 43)
	s := Server{}
	s.Config.GatewayToken = secret
	s.Config.WorkspaceToken = secret
	router := s.Router()
	router.GET("/v1/panic", func(*gin.Context) { panic("private payload") })
	for _, duplicate := range []string{"X-Gateway-Token", "X-Clerk-Sub", "X-Openlet-User-ID"} {
		request := httptest.NewRequest(http.MethodGet, "/v1/unknown", nil)
		request.Header.Set("X-Gateway-Token", secret)
		request.Header.Set("X-Clerk-Sub", "user_test")
		request.Header.Set("X-Openlet-User-ID", uuid.NewString())
		request.Header.Add(duplicate, request.Header.Get(duplicate))
		response := httptest.NewRecorder()
		router.ServeHTTP(response, request)
		if response.Code != 401 {
			t.Fatalf("duplicate %s admitted: %d", duplicate, response.Code)
		}
	}
	for _, path := range []string{"/v1/unknown", "/v1/me/", "/v1/panic"} {
		request := httptest.NewRequest(http.MethodGet, path, nil)
		request.Header.Set("X-Gateway-Token", secret)
		request.Header.Set("X-Clerk-Sub", "user_test")
		request.Header.Set("X-Openlet-User-ID", uuid.NewString())
		request.Header.Set("X-Request-ID", "untrusted request ID")
		response := httptest.NewRecorder()
		router.ServeHTTP(response, request)
		expected := 404
		if path == "/v1/panic" {
			expected = 500
		}
		if response.Code != expected || response.Header().Get("Location") != "" || strings.Contains(response.Body.String(), "private payload") {
			t.Fatalf("%s: status=%d body=%s", path, response.Code, response.Body)
		}
		if id, err := uuid.Parse(response.Header().Get("X-Request-ID")); err != nil || id == uuid.Nil {
			t.Fatal("request ID was not generated")
		}
	}
	request := httptest.NewRequest(http.MethodGet, "/internal/v1/unknown", nil)
	request.Header.Set("Authorization", "Bearer "+secret)
	request.Header.Add("Authorization", "Bearer "+secret)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != 401 {
		t.Fatalf("duplicate internal credentials admitted: %d", response.Code)
	}
}

func TestGinJSONBoundaryDoesNotAutoWrite(t *testing.T) {
	router := gin.New()
	router.POST("/body", func(c *gin.Context) {
		var value struct {
			Name string `json:"name"`
		}
		if decode(c.Writer, c.Request, &value) != nil {
			Error(c.Writer, c.Request, 400, "VALIDATION", "invalid body")
			return
		}
		c.Status(204)
	})
	for _, body := range []string{`{"unknown":true}`, `{"name":"ok"}{}`, `{"name":"` + strings.Repeat("x", 16384) + `"}`} {
		response := httptest.NewRecorder()
		router.ServeHTTP(response, httptest.NewRequest(http.MethodPost, "/body", strings.NewReader(body)))
		if response.Code != 400 || !strings.Contains(response.Body.String(), "VALIDATION") {
			t.Fatalf("invalid JSON accepted or auto-written: %d", response.Code)
		}
	}
}
