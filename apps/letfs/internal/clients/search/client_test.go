package search

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func TestDeletePointsRequiresExactAcknowledgmentAndScope(t *testing.T) {
	source := uuid.New()
	for _, scenario := range []struct {
		name, body string
		code       int
		ok         bool
	}{
		{"completed", `{"result":{"status":"completed"}}`, 200, true},
		{"missing collection", "", 404, true},
		{"unconfirmed", `{"result":{"status":"acknowledged"}}`, 200, false},
		{"malformed", `{`, 200, false},
		{"outage", `{}`, 503, false},
		{"redirect", `{}`, 307, false},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				require.Equal(t, "POST", r.Method)
				require.Equal(t, "/collections/files/points/delete?wait=true", r.URL.RequestURI())
				require.Equal(t, "isolated-key", r.Header.Get("api-key"))
				var body map[string]any
				require.NoError(t, json.NewDecoder(r.Body).Decode(&body))
				require.Equal(t, map[string]any{"filter": map[string]any{"must": []any{
					map[string]any{"key": "source_id", "match": map[string]any{"value": source.String()}},
					map[string]any{"key": "generation", "match": map[string]any{"value": float64(7)}},
					map[string]any{"key": "embedding_model", "match": map[string]any{"value": "embedding-v1"}},
					map[string]any{"key": "vector_dimension", "match": map[string]any{"value": float64(8)}},
				}}}, body)
				w.WriteHeader(scenario.code)
				_, _ = w.Write([]byte(scenario.body))
			}))
			defer server.Close()
			client, err := New(server.URL, "isolated-key")
			require.NoError(t, err)
			err = client.DeletePoints(t.Context(), "files", source, 7, "embedding-v1", 8)
			if scenario.ok {
				require.NoError(t, err)
			} else {
				require.Error(t, err)
			}
			ctx, cancel := context.WithCancel(t.Context())
			cancel()
			require.Error(t, client.DeletePoints(ctx, "files", source, 7, "embedding-v1", 8))
		})
	}
}
