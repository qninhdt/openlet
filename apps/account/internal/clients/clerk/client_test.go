package clerk

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestMetadataPatchOnlyOwnsInternalID(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "PATCH" || r.URL.Path != "/users/user_subject/metadata" || r.Header.Get("Authorization") != "Bearer test-secret" {
			t.Error("wrong Clerk request")
		}
		var got map[string]map[string]string
		if json.NewDecoder(r.Body).Decode(&got) != nil || len(got) != 1 || len(got["public_metadata"]) != 1 || got["public_metadata"]["openlet_user_id"] != "internal-id" {
			t.Error("metadata scope changed")
		}
		w.WriteHeader(200)
	}))
	defer server.Close()
	if e := (Client{BaseURL: server.URL, Secret: "test-secret"}).PublishUserIdentity(context.Background(), "user_subject", "internal-id"); e != nil {
		t.Fatal(e)
	}
}

func TestVerifiedEmailsPreservesCancellation(t *testing.T) {
	for _, deadline := range []bool{false, true} {
		t.Run(map[bool]string{false: "canceled", true: "deadline"}[deadline], func(t *testing.T) {
			entered := make(chan struct{})
			stopped := make(chan struct{})
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				close(entered)
				select {
				case <-r.Context().Done():
				case <-stopped:
				}
			}))
			defer server.Close()
			defer close(stopped)
			ctx, cancel := context.WithTimeout(t.Context(), time.Second)
			defer cancel()
			result := make(chan error, 1)
			go func() { _, err := (Client{BaseURL: server.URL}).VerifiedEmails(ctx, "subject"); result <- err }()
			select {
			case <-entered:
			case <-ctx.Done():
				t.Fatal("provider did not receive request")
			}
			want := context.DeadlineExceeded
			if !deadline {
				want = context.Canceled
				cancel()
			}
			select {
			case err := <-result:
				if !errors.Is(err, want) {
					t.Fatalf("want %v, got %v", want, err)
				}
			case <-time.After(3 * time.Second):
				t.Fatal("Clerk request did not stop")
			}
		})
	}
}
func TestEmailsRequireVerifiedStatus(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"email_addresses":[{"email_address":"a@example.test","verification":{"status":"verified"}},{"email_address":"b@example.test","verification":{"status":"unverified"}}]}`))
	}))
	defer server.Close()
	got, e := (Client{BaseURL: server.URL}).VerifiedEmails(context.Background(), "subject")
	if e != nil || len(got) != 1 || got[0] != "a@example.test" {
		t.Fatal(got, e)
	}
}
