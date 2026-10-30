package e2e

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

var client = &http.Client{Timeout: 30 * time.Second}

func call(t *testing.T, method, url string, data any, headers map[string]string) (int, []byte) {
	t.Helper()
	var body io.Reader
	if data != nil {
		b, e := json.Marshal(data)
		if e != nil {
			t.Fatal(e)
		}
		body = bytes.NewReader(b)
	}
	r, e := http.NewRequest(method, url, body)
	if e != nil {
		t.Fatal(e)
	}
	r.Header.Set("Content-Type", "application/json")
	for k, v := range headers {
		r.Header.Set(k, v)
	}
	res, e := client.Do(r)
	if e != nil {
		t.Fatal(e)
	}
	defer res.Body.Close()
	b, e := io.ReadAll(res.Body)
	if e != nil {
		t.Fatal(e)
	}
	recordContract(t, method, url, res.StatusCode, b)
	return res.StatusCode, b
}
func token(t *testing.T, claims map[string]any, bad bool) string {
	t.Helper()
	s, b := call(t, "POST", "http://issuer:8080/token", map[string]any{"claims": claims, "bad_signature": bad}, nil)
	if s != 200 {
		t.Fatal(s, string(b))
	}
	var v struct {
		Token string `json:"token"`
	}
	if json.Unmarshal(b, &v) != nil {
		t.Fatal("invalid token response")
	}
	return v.Token
}
func TestGateway(t *testing.T) {
	good := token(t, nil, false)
	cases := []struct {
		name, path, token string
		want              int
	}{
		{"missing", "/v1/me", "", 401}, {"valid", "/v1/me", good, 404},
		{"signature", "/v1/me", token(t, nil, true), 401},
		{"issuer", "/v1/me", token(t, map[string]any{"iss": "https://wrong.example"}, false), 401},
		// Envoy's native JWT filter distinguishes disallowed audience with 403.
		{"audience", "/v1/me", token(t, map[string]any{"aud": "wrong"}, false), 403},
		{"expiry", "/v1/me", token(t, map[string]any{"exp": time.Now().Add(-time.Hour).Unix()}, false), 401},
		{"missing-expiry", "/v1/me", token(t, map[string]any{"exp": nil}, false), 401},
		{"bootstrap-normal", "/v1/me", token(t, map[string]any{"openlet_user_id": nil}, false), 403},
		{"bootstrap-onboarding", "/v1/onboarding", token(t, map[string]any{"openlet_user_id": nil}, false), 404},
		{"internal", "/internal/v1/quota-buckets/ensure", good, 404},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			h := map[string]string{"X-Openlet-User-ID": "019ad06b-7d00-7000-8000-000000000099", "X-Clerk-Sub": "forged", "X-Gateway-Token": "forged"}
			if c.token != "" {
				h["Authorization"] = "Bearer " + c.token
			}
			s, b := call(t, "GET", "http://envoy:8080"+c.path, nil, h)
			if s != c.want {
				t.Fatalf("got %d want %d: %s", s, c.want, b)
			}
		})
	}
	// The app requires the real gateway credential and forwarded subject; 404 proves both checks passed.
	s, b := call(t, "GET", "http://user:8080/v1/me", nil, map[string]string{"X-Openlet-User-ID": "019ad06b-7d00-7000-8000-000000000099", "X-Clerk-Sub": "forged"})
	if s != 401 {
		t.Fatalf("direct bypass: %d %s", s, b)
	}
}
func TestProvisioning(t *testing.T) {
	secret, e := os.ReadFile("/run/secrets/workspace_service_token")
	if e != nil {
		t.Fatal(e)
	}
	h := map[string]string{"Authorization": "Bearer " + strings.TrimSpace(string(secret))}
	id := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	bucket := "019ad06b-7d00-7000-8000-" + id
	fs := "019ad06b-7d00-7001-8000-" + id
	root := "019ad06b-7d00-7002-8000-" + id
	data := map[string]string{"id": bucket, "provision_key": "test-bucket-" + id, "limit_bytes": "1024"}
	for _, invalid := range []string{"-1", "00", "1.0", "9223372036854775808"} {
		bad := map[string]string{"id": bucket, "provision_key": "invalid-" + id, "limit_bytes": invalid}
		s, b := call(t, "POST", "http://letfs:8080/internal/v1/quota-buckets/ensure", bad, h)
		if s != 400 {
			t.Fatalf("accepted invalid limit: %d %s", s, b)
		}
	}
	s, _ := call(t, "POST", "http://letfs:8080/internal/v1/quota-buckets/ensure", data, nil)
	if s != 401 {
		t.Fatal("unauthenticated provisioning accepted", s)
	}
	for i := 0; i < 2; i++ {
		s, b := call(t, "POST", "http://letfs:8080/internal/v1/quota-buckets/ensure", data, h)
		if s != 200 {
			t.Fatal(s, string(b))
		}
	}
	data["limit_bytes"] = "1025"
	s, _ = call(t, "POST", "http://letfs:8080/internal/v1/quota-buckets/ensure", data, h)
	if s != 409 {
		t.Fatal("changed quota input accepted", s)
	}
	f := map[string]string{"id": fs, "bucket_id": bucket, "root_id": root, "provision_key": "test-fs-" + id, "root_name": "drive"}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			s, b := call(t, "POST", "http://letfs:8080/internal/v1/filesystems/ensure", f, h)
			if s != 200 {
				t.Error(s, string(b))
			}
		}()
	}
	wg.Wait()
	f["root_name"] = "different"
	s, _ = call(t, "POST", "http://letfs:8080/internal/v1/filesystems/ensure", f, h)
	if s != 409 {
		t.Fatal("changed root accepted", s)
	}
}
func TestRateLimit(t *testing.T) {
	tok := token(t, nil, false)
	counts := map[int]int{}
	for i := 0; i < 400; i++ {
		s, _ := call(t, "GET", "http://envoy:8080/v1/me", nil, map[string]string{"Authorization": "Bearer " + tok})
		counts[s]++
	}
	if counts[429] == 0 {
		t.Fatal("configured burst never rejected", counts)
	}
}

func TestReadiness(t *testing.T) {
	deadline := time.Now().Add(90 * time.Second)
	for _, service := range []string{"user", "workspace", "letfs"} {
		for {
			res, e := client.Get("http://" + service + ":8080/ready")
			if e == nil {
				res.Body.Close()
				if res.StatusCode == 204 {
					break
				}
			}
			if time.Now().After(deadline) {
				t.Fatalf("%s readiness deadline exceeded: %v", service, e)
			}
			time.Sleep(200 * time.Millisecond)
		}
	}
}
