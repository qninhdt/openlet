package main

import (
	"crypto/subtle"
	"encoding/json"
	"net/http"
	"os"
	"strings"
	"sync"
)

type testClerkUser struct {
	Email         string         `json:"email"`
	Verified      bool           `json:"verified"`
	Metadata      map[string]any `json:"public_metadata"`
	FailPatch     int            `json:"fail_patch"`
	PatchAttempts int            `json:"patch_attempts"`
}

func clerkRoutes(mux *http.ServeMux) {
	secret, e := os.ReadFile("/run/secrets/clerk_secret_key")
	if e != nil {
		panic("missing Clerk test credential")
	}
	var mu sync.Mutex
	users := map[string]*testClerkUser{}
	mux.HandleFunc("PUT /control/users/{id}", func(w http.ResponseWriter, r *http.Request) {
		var v testClerkUser
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 16384)).Decode(&v) != nil {
			w.WriteHeader(400)
			return
		}
		if v.Metadata == nil {
			v.Metadata = map[string]any{}
		}
		mu.Lock()
		users[r.PathValue("id")] = &v
		mu.Unlock()
		w.WriteHeader(204)
	})
	mux.HandleFunc("GET /control/users/{id}", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		v := users[r.PathValue("id")]
		if v == nil {
			w.WriteHeader(404)
			return
		}
		_ = json.NewEncoder(w).Encode(v)
	})
	auth := func(w http.ResponseWriter, r *http.Request) bool {
		if subtle.ConstantTimeCompare([]byte(r.Header.Get("Authorization")), []byte("Bearer "+strings.TrimSpace(string(secret)))) != 1 {
			w.WriteHeader(401)
			return false
		}
		return true
	}
	mux.HandleFunc("GET /v1/users/{id}", func(w http.ResponseWriter, r *http.Request) {
		if !auth(w, r) {
			return
		}
		mu.Lock()
		defer mu.Unlock()
		v := users[r.PathValue("id")]
		if v == nil {
			w.WriteHeader(404)
			return
		}
		status := "unverified"
		if v.Verified {
			status = "verified"
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"email_addresses": []any{map[string]any{"email_address": v.Email, "verification": map[string]string{"status": status}}}, "public_metadata": v.Metadata})
	})
	mux.HandleFunc("PATCH /v1/users/{id}/metadata", func(w http.ResponseWriter, r *http.Request) {
		if !auth(w, r) {
			return
		}
		var in struct {
			Metadata map[string]any `json:"public_metadata"`
		}
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 16384)).Decode(&in) != nil {
			w.WriteHeader(400)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		v := users[r.PathValue("id")]
		if v == nil {
			w.WriteHeader(404)
			return
		}
		v.PatchAttempts++
		if v.FailPatch > 0 {
			v.FailPatch--
			w.WriteHeader(503)
			return
		}
		for k, value := range in.Metadata {
			v.Metadata[k] = value
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"public_metadata": v.Metadata})
	})
}
