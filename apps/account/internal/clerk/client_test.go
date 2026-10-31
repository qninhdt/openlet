package clerk

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
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
	if e := (Client{BaseURL: server.URL, Secret: "test-secret"}).PublishUserID(context.Background(), "user_subject", "internal-id"); e != nil {
		t.Fatal(e)
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
