package e2e

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"testing"
	"time"
)

func jsonMap(t *testing.T, b []byte) map[string]any {
	t.Helper()
	var v map[string]any
	if e := json.Unmarshal(b, &v); e != nil {
		t.Fatalf("invalid JSON: %s", b)
	}
	return v
}
func requireStatus(t *testing.T, s, want int, b []byte) {
	t.Helper()
	if s != want {
		t.Fatalf("got %d want %d: %s", s, want, b)
	}
}
func onboard(t *testing.T, subject, email, key string, failPatch int) (string, string, string) {
	t.Helper()
	s, b := call(t, "PUT", "http://issuer:8080/control/users/"+subject, map[string]any{"email": email, "verified": true, "public_metadata": map[string]any{"other": "preserve"}, "fail_patch": failPatch}, nil)
	requireStatus(t, s, 204, b)
	bootstrap := token(t, map[string]any{"sub": subject, "openlet_user_id": nil}, false)
	h := map[string]string{"Authorization": "Bearer " + bootstrap, "Idempotency-Key": key}
	s, b = call(t, "POST", "http://envoy:8080/v1/onboarding", nil, h)
	if s != 202 && s != 200 {
		t.Fatal(s, string(b))
	}
	deadline := time.Now().Add(30 * time.Second)
	var v map[string]any
	for {
		s, b = call(t, "GET", "http://envoy:8080/v1/onboarding", nil, h)
		requireStatus(t, s, 200, b)
		v = jsonMap(t, b)
		if v["state"] == "succeeded" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("onboarding deadline", string(b))
		}
		time.Sleep(100 * time.Millisecond)
	}
	id := v["user_id"].(string)
	ws := v["workspace_id"].(string)
	s, b = call(t, "GET", "http://issuer:8080/control/users/"+subject, nil, nil)
	requireStatus(t, s, 200, b)
	clerk := jsonMap(t, b)
	metadata := clerk["public_metadata"].(map[string]any)
	if metadata["openlet_user_id"] != id || metadata["other"] != "preserve" {
		t.Fatal("metadata was lost or misbound", metadata)
	}
	if failPatch > 0 && clerk["patch_attempts"].(float64) <= float64(failPatch) {
		t.Fatal("Clerk retry was not exercised")
	}
	fresh := token(t, map[string]any{"sub": subject, "openlet_user_id": id}, false)
	s, b = call(t, "GET", "http://envoy:8080/v1/me", nil, map[string]string{"Authorization": "Bearer " + fresh, "X-Openlet-User-ID": "019ad06b-7d00-7000-8000-000000000099"})
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["id"] != id {
		t.Fatal("forged ID header influenced profile")
	}
	// A second onboarding response returns the original IDs and creates no new workspace.
	s, b = call(t, "POST", "http://envoy:8080/v1/onboarding", nil, h)
	requireStatus(t, s, 200, b)
	again := jsonMap(t, b)
	if again["user_id"] != id || again["workspace_id"] != ws {
		t.Fatal("onboarding identity changed")
	}
	saveHistory(t, "onboard/"+subject, "OnboardUser")
	if directoryEnabled() {
		db := workspaceDB(t)
		var actor, key string
		if e := db.QueryRow(t.Context(), "SELECT actor_id::text,request_key::text FROM operations WHERE workspace_id=$1 AND kind='create'", ws).Scan(&actor, &key); e != nil {
			t.Fatal(e)
		}
		saveHistory(t, "create-workspace/"+actor+"/"+key, "CreateWorkspace")
	}
	return fresh, id, ws
}
func TestIdentityWorkspace(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	owner, ownerID, ws := onboard(t, "user_owner_"+suffix, "owner-"+suffix+"@example.test", "019ad06b-7d00-7000-8100-"+suffix, 1)
	editor, editorID, _ := onboard(t, "user_editor_"+suffix, "editor-"+suffix+"@example.test", "019ad06b-7d00-7000-8200-"+suffix, 0)
	h := map[string]string{"Authorization": "Bearer " + owner}
	base := "http://envoy:8080/v1/workspaces/" + ws
	s, b := call(t, "GET", base, nil, h)
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["role"] != "owner" {
		t.Fatal("initial owner missing")
	}
	s, b = call(t, "PATCH", "http://envoy:8080/v1/me", map[string]string{"display_name": "invalid\x00name"}, h)
	requireStatus(t, s, 400, b)
	s, b = call(t, "POST", base+"/invitations", map[string]string{"email": "editor-" + suffix + "@example.test", "role": "owner"}, h)
	requireStatus(t, s, 400, b)
	s, b = call(t, "POST", base+"/invitations", map[string]string{"email": "EDITOR-" + suffix + "@example.test", "role": "editor"}, h)
	requireStatus(t, s, 201, b)
	invite := jsonMap(t, b)
	inviteToken := invite["token"].(string)
	s, b = call(t, "POST", "http://envoy:8080/v1/invitations/accept", map[string]string{"token": inviteToken}, h)
	requireStatus(t, s, 403, b)
	eh := map[string]string{"Authorization": "Bearer " + editor}
	s, b = call(t, "POST", "http://envoy:8080/v1/invitations/accept", map[string]string{"token": inviteToken}, eh)
	requireStatus(t, s, 200, b)
	s, b = call(t, "GET", base+"/members", nil, eh)
	requireStatus(t, s, 200, b)
	if strings.Contains(string(b), "email") || strings.Contains(string(b), "clerk") || strings.Contains(string(b), "onboarding") {
		t.Fatal("private user fields leaked into members", string(b))
	}
	items := jsonMap(t, b)["items"].([]any)
	if len(items) != 2 {
		t.Fatal("member count", len(items))
	}
	s, b = call(t, "DELETE", base+"/members/"+ownerID, nil, h)
	requireStatus(t, s, 409, b)
	s, b = call(t, "POST", base+"/ownership", map[string]string{"user_id": editorID}, eh)
	requireStatus(t, s, 403, b)
	s, b = call(t, "POST", base+"/ownership", map[string]string{"user_id": editorID}, h)
	requireStatus(t, s, 204, b)
	s, b = call(t, "GET", base, nil, eh)
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["role"] != "owner" {
		t.Fatal("transfer failed")
	}
	s, b = call(t, "POST", base+"/invitations", map[string]string{"email": "another@example.test", "role": "viewer"}, h)
	requireStatus(t, s, 403, b)
	s, b = call(t, "DELETE", base+"/members/"+ownerID, nil, eh)
	requireStatus(t, s, 204, b)
	s, b = call(t, "GET", base, nil, h)
	requireStatus(t, s, 404, b)
	// Accepted invitation replay cannot re-add the removed invitee.
	s, b = call(t, "POST", base+"/ownership", map[string]string{"user_id": ownerID}, eh)
	requireStatus(t, s, 404, b)
	// After ownership returns through a fresh invitation, removing the old invitee leaves its token spent.
	s, b = call(t, "POST", base+"/invitations", map[string]string{"email": "owner-" + suffix + "@example.test", "role": "editor"}, eh)
	requireStatus(t, s, 201, b)
	newToken := jsonMap(t, b)["token"].(string)
	s, b = call(t, "POST", "http://envoy:8080/v1/invitations/accept", map[string]string{"token": newToken}, h)
	requireStatus(t, s, 200, b)
	s, b = call(t, "POST", base+"/ownership", map[string]string{"user_id": ownerID}, eh)
	requireStatus(t, s, 204, b)
	s, b = call(t, "DELETE", base+"/members/"+editorID, nil, h)
	requireStatus(t, s, 204, b)
	s, b = call(t, "POST", "http://envoy:8080/v1/invitations/accept", map[string]string{"token": inviteToken}, eh)
	requireStatus(t, s, 409, b)

	// Revocation and expiry are terminal even for the correct verified email.
	for _, mode := range []string{"revoked", "expired"} {
		s, b = call(t, "POST", base+"/invitations", map[string]string{"email": "editor-" + suffix + "@example.test", "role": "viewer"}, h)
		requireStatus(t, s, 201, b)
		invitation := jsonMap(t, b)
		raw := invitation["token"].(string)
		inviteID := invitation["invitation"].(map[string]any)["id"].(string)
		if mode == "revoked" {
			s, b = call(t, "DELETE", base+"/invitations/"+inviteID, nil, h)
			requireStatus(t, s, 204, b)
		} else {
			db := workspaceDB(t)
			if _, e := db.Exec(context.Background(), "UPDATE workspace_invitations SET expires_at=now()-interval '1 second' WHERE id=$1", inviteID); e != nil {
				t.Fatal(e)
			}
		}
		s, b = call(t, "POST", "http://envoy:8080/v1/invitations/accept", map[string]string{"token": raw}, eh)
		requireStatus(t, s, 409, b)
	}
}
