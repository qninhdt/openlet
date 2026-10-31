package http

import (
	"context"
	"github.com/gin-gonic/gin"
	"io"
	"net/http"
	"net/http/httptest"
	"openlet/apps/workspace/internal/config"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestTrustedIdentityBoundary(t *testing.T) {
	secret := strings.Repeat("x", 43)
	s := Server{Config: config.Config{GatewayToken: secret}}
	h := gin.New()
	h.Use(s.Gateway)
	h.GET("/v1/me", func(c *gin.Context) { c.Status(204) })
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

func TestFileDownloadRedirectDoesNotRelayObjectBytes(t *testing.T) {
	objectRequests := 0
	object := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		objectRequests++
		w.Write([]byte("object bytes must never cross the workspace facade"))
	}))
	defer object.Close()
	signedURL := object.URL + "/immutable-key?X-Amz-Signature=test-only"
	backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Range") != "bytes=1-2" {
			t.Error("range was lost")
		}
		w.Header().Set("Location", signedURL)
		w.Header().Set("ETag", "\"7\"")
		w.WriteHeader(http.StatusTemporaryRedirect)
	}))
	defer backend.Close()
	server := Server{Config: config.Config{LetfsURL: backend.URL}}
	request := httptest.NewRequest(http.MethodGet, "/content?revision=7", nil)
	request.Header.Set("X-Openlet-User-ID", "019ad06b-7d00-7000-8000-000000000001")
	request.Header.Set("Range", "bytes=1-2")
	response := httptest.NewRecorder()
	router := gin.New()
	router.GET("/content", func(c *gin.Context) {
		server.proxyLetfs(c, http.MethodPost, "/internal/content", strings.NewReader("{}"))
	})
	router.ServeHTTP(response, request)
	if response.Code != http.StatusTemporaryRedirect || response.Header().Get("Location") != signedURL || response.Header().Get("ETag") != "\"7\"" {
		t.Fatalf("redirect changed: status=%d location=%q revision=%q", response.Code, response.Header().Get("Location"), response.Header().Get("ETag"))
	}
	if objectRequests != 0 || response.Body.Len() != 0 {
		t.Fatal("workspace fetched object bytes")
	}
	if response.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("capability may be cached")
	}
}

func TestArchiveProxyAbortsIncompleteBodyAndCancelsDisconnectedReads(t *testing.T) {
	for _, mode := range []string{"failure", "disconnect"} {
		t.Run(mode, func(t *testing.T) {
			started := make(chan struct{})
			canceled := make(chan struct{})
			backend := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/zip")
				w.WriteHeader(http.StatusOK)
				_, _ = w.Write([]byte("PK incomplete archive"))
				w.(http.Flusher).Flush()
				close(started)
				if mode == "failure" {
					panic(http.ErrAbortHandler)
				}
				<-r.Context().Done()
				close(canceled)
			}))
			defer backend.Close()
			app := Server{Config: config.Config{LetfsURL: backend.URL}}
			router := gin.New()
			router.Use(observe)
			router.GET("/archive", func(c *gin.Context) { app.proxyLetfs(c, "POST", "/internal/archive", strings.NewReader("{}")) })
			facade := httptest.NewServer(router)
			defer facade.Close()
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			req, err := http.NewRequestWithContext(ctx, "GET", facade.URL+"/archive", nil)
			req.Header.Set("X-Openlet-User-ID", "019ad06b-7d00-7000-8000-000000000001")
			if err != nil {
				t.Fatal(err)
			}
			result := make(chan error, 1)
			go func() {
				res, err := http.DefaultClient.Do(req)
				if err == nil {
					defer res.Body.Close()
					_, err = io.ReadAll(res.Body)
				}
				result <- err
			}()
			select {
			case <-started:
			case <-ctx.Done():
				t.Fatal("upstream did not start")
			}
			if mode == "disconnect" {
				cancel()
				select {
				case <-canceled:
				case <-time.After(5 * time.Second):
					t.Fatal("disconnected read was not canceled")
				}
			}
			select {
			case err := <-result:
				if err == nil {
					t.Fatal("incomplete archive was delivered as a complete response")
				}
			case <-time.After(5 * time.Second):
				t.Fatal("archive request did not finish")
			}
		})
	}
}
