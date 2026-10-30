package letfs

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/google/uuid"
)

func TestEnsureValidatesReturnedScope(t *testing.T) {
	id := uuid.Must(uuid.NewV7())
	wrong := uuid.Must(uuid.NewV7())
	for _, resultID := range []uuid.UUID{id, wrong} {
		t.Run(resultID.String(), func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("Authorization") != "Bearer test" || r.URL.Path != "/internal/v1/quota-buckets/ensure" {
					t.Error("invalid request contract")
				}
				_ = json.NewEncoder(w).Encode(Bucket{ID: resultID, LimitBytes: "100", UsedBytes: "0", State: "active"})
			}))
			defer srv.Close()
			c := Client{BaseURL: srv.URL, Token: "test"}
			_, e := c.EnsureBucket(context.Background(), BucketInput{ID: id, ProvisionKey: "test", LimitBytes: "100"})
			if (e != nil) != (resultID != id) {
				t.Fatalf("scope result error: %v", e)
			}
		})
	}
}
