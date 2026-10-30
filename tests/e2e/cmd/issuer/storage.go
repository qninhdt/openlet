package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"sync"
	"time"
)

// Only the test issuer exposes this fault boundary; every byte still reaches the real S3 server.
func storageRoutes(mux *http.ServeMux) {
	var mu sync.Mutex
	var blocked, seen, blockedGet, seenGet, failGet bool
	var lost, lostComplete int
	release := make(chan struct{})
	mux.HandleFunc("PUT /control/storage", func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			BlockCopy    bool `json:"block_copy"`
			BlockGet     bool `json:"block_get"`
			FailGet      bool `json:"fail_get"`
			LoseCopy     int  `json:"lose_copy"`
			LoseComplete int  `json:"lose_complete"`
		}
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 1024)).Decode(&in) != nil {
			w.WriteHeader(400)
			return
		}
		mu.Lock()
		close(release)
		release = make(chan struct{})
		blocked = in.BlockCopy
		blockedGet = in.BlockGet
		failGet = in.FailGet
		lost = in.LoseCopy
		lostComplete = in.LoseComplete
		seen = false
		seenGet = false
		mu.Unlock()
		w.WriteHeader(204)
	})
	mux.HandleFunc("GET /control/storage", func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		_ = json.NewEncoder(w).Encode(map[string]bool{"copy_seen": seen, "get_seen": seenGet})
	})
	target, _ := url.Parse("http://storage:8333")
	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.Transport = &http.Transport{ResponseHeaderTimeout: 120 * time.Second}
	proxy.ModifyResponse = func(r *http.Response) error {
		isCopy := r.Request.Header.Get("X-Amz-Copy-Source") != ""
		isComplete := r.Request.Method == http.MethodPost && r.Request.URL.Query().Get("uploadId") != ""
		if (!isCopy && !isComplete) || r.StatusCode >= 300 {
			return nil
		}
		mu.Lock()
		drop := (isCopy && lost > 0) || (isComplete && lostComplete > 0)
		if isCopy && lost > 0 {
			lost--
		}
		if isComplete && lostComplete > 0 {
			lostComplete--
		}
		mu.Unlock()
		if drop {
			_, _ = io.Copy(io.Discard, r.Body)
			_ = r.Body.Close()
			body := "<Error><Code>SlowDown</Code><Message>Injected lost acknowledgment</Message></Error>"
			r.StatusCode = 503
			r.Body = io.NopCloser(strings.NewReader(body))
			r.ContentLength = int64(len(body))
			r.Header.Set("Content-Length", "")
			r.Header.Del("Content-Length")
		}
		return nil
	}
	go func() {
		_ = (&http.Server{Addr: ":8333", ReadHeaderTimeout: 5 * time.Second, Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Method == http.MethodGet {
				mu.Lock()
				wait, ch, fail := blockedGet, release, failGet
				if wait {
					seenGet = true
				}
				mu.Unlock()
				if fail {
					w.WriteHeader(http.StatusServiceUnavailable)
					return
				}
				if wait {
					select {
					case <-ch:
					case <-r.Context().Done():
						return
					}
				}
			}
			if r.Header.Get("X-Amz-Copy-Source") != "" {
				mu.Lock()
				seen = true
				wait := blocked
				ch := release
				mu.Unlock()
				if wait {
					select {
					case <-ch:
					case <-r.Context().Done():
						return
					}
				}
			}
			proxy.ServeHTTP(w, r)
		})}).ListenAndServe()
	}()
}
