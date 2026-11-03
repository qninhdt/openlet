package search

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"io"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func TestOpenRouterSDKWireContract(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		require.Equal(t, http.MethodPost, r.Method)
		require.Equal(t, "Bearer isolated-key", r.Header.Get("Authorization"))
		require.Equal(t, "application/json", r.Header.Get("Content-Type"))
		var body map[string]any
		require.NoError(t, json.NewDecoder(r.Body).Decode(&body))
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/api/v1/embeddings":
			require.Equal(t, map[string]any{"model": "embedding-v1", "input": "volcano", "dimensions": float64(2), "encoding_format": "float"}, body)
			_, _ = fmt.Fprint(w, `{"object":"list","model":"embedding-v1","data":[{"object":"embedding","index":0,"embedding":[0.5,-0.5]}]}`)
		case "/api/v1/rerank":
			require.Equal(t, map[string]any{"model": "rerank-v1", "query": "volcano", "documents": []any{"first", "second"}, "top_n": float64(2)}, body)
			_, _ = fmt.Fprint(w, `{"model":"rerank-v1","results":[{"index":1,"relevance_score":0.9},{"index":0,"relevance_score":0.1}]}`)
		default:
			t.Errorf("unexpected provider path %q", r.URL.Path)
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer server.Close()
	ai, err := NewAI(AIConfig{URL: server.URL + "/api/v1/", Key: "isolated-key", RerankModel: "rerank-v1", AllowLocal: true})
	require.NoError(t, err)
	vector, err := ai.Embed(t.Context(), " volcano ", "embedding-v1", 2)
	require.NoError(t, err)
	require.Equal(t, []float64{0.5, -0.5}, vector)
	order, err := ai.Rerank(t.Context(), " volcano ", []string{"first", "second"})
	require.NoError(t, err)
	require.Equal(t, []int{1, 0}, order)
}

func TestOpenRouterSDKRejectsInvalidResultsAndRedactsFailures(t *testing.T) {
	for _, tc := range []struct {
		name, body string
		code       int
		rerank     bool
	}{
		{"embedding outage", `{"error":{"message":"private-provider-detail"}}`, 503, false},
		{"rerank outage", `{"error":{"message":"private-provider-detail"}}`, 503, true},
		{"malformed", `{private-provider-detail`, 200, false},
		{"missing vector", `{"data":[]}`, 200, false},
		{"wrong dimension", `{"data":[{"embedding":[1]}]}`, 200, false},
		{"extra vector", `{"data":[{"embedding":[1,0]},{"embedding":[0,1]}]}`, 200, false},
		{"base64 vector", `{"data":[{"embedding":"AACAPwAAAAA="}]}`, 200, false},
		{"overflow vector", `{"data":[{"embedding":[1e999,0]}]}`, 200, false},
		{"missing ranking", `{"results":[]}`, 200, true},
		{"duplicate rank", `{"results":[{"index":0,"relevance_score":1},{"index":0,"relevance_score":0}]}`, 200, true},
		{"negative rank", `{"results":[{"index":-1,"relevance_score":1},{"index":0,"relevance_score":0}]}`, 200, true},
		{"out of range", `{"results":[{"index":2,"relevance_score":1},{"index":0,"relevance_score":0}]}`, 200, true},
		{"overflow score", `{"results":[{"index":1,"relevance_score":1e999},{"index":0,"relevance_score":0}]}`, 200, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var requests atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests.Add(1)
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(tc.code)
				_, _ = fmt.Fprint(w, tc.body)
			}))
			defer server.Close()
			ai, err := NewAI(AIConfig{URL: server.URL, Key: "isolated-key", RerankModel: "rerank-v1", AllowLocal: true})
			require.NoError(t, err)
			if tc.rerank {
				_, err = ai.Rerank(t.Context(), "private-query", []string{"private-first", "private-second"})
			} else {
				_, err = ai.Embed(t.Context(), "private-query", "embedding-v1", 2)
			}
			require.Equal(t, apperr.Unavailable, apperr.KindOf(err))
			require.NotContains(t, err.Error(), "private-")
			require.NotContains(t, err.Error(), "isolated-key")
			require.Equal(t, int32(1), requests.Load(), "SDK must not retry interactive search requests")
		})
	}
}

func TestOpenRouterSDKPropagatesCancellationAndDeadline(t *testing.T) {
	for _, operation := range []string{"embed", "rerank"} {
		for _, deadline := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/deadline=%t", operation, deadline), func(t *testing.T) {
				started, stopped := make(chan struct{}), make(chan struct{})
				server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					_, _ = io.Copy(io.Discard, r.Body)
					close(started)
					select {
					case <-r.Context().Done():
					case <-t.Context().Done():
					}
					close(stopped)
				}))
				defer server.Close()
				ai, err := NewAI(AIConfig{URL: server.URL, Key: "isolated-key", RerankModel: "rerank-v1", AllowLocal: true})
				require.NoError(t, err)
				ctx, cancel := context.WithCancel(t.Context())
				if deadline {
					cancel()
					ctx, cancel = context.WithTimeout(t.Context(), time.Second)
				}
				defer cancel()
				result := make(chan error, 1)
				go func() {
					if operation == "embed" {
						_, err := ai.Embed(ctx, "volcano", "embedding-v1", 2)
						result <- err
					} else {
						_, err := ai.Rerank(ctx, "volcano", []string{"first", "second"})
						result <- err
					}
				}()
				select {
				case <-started:
				case <-time.After(3 * time.Second):
					t.Fatal("provider request did not start")
				}
				if !deadline {
					cancel()
				}
				select {
				case err := <-result:
					require.Equal(t, apperr.Unavailable, apperr.KindOf(err))
				case <-time.After(3 * time.Second):
					t.Fatal("SDK request ignored cancellation/deadline")
				}
				select {
				case <-stopped:
				case <-time.After(3 * time.Second):
					t.Fatal("provider request was not canceled")
				}
			})
		}
	}
}
