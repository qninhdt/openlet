package sdk

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
	"time"
)

func TestSignCentrifugoToken(t *testing.T) {
	secret := "test-centrifugo-secret"
	tok, exp, err := SignCentrifugoToken(secret, "user-123", "", time.Hour)
	if err != nil {
		t.Fatalf("connect token: %v", err)
	}
	if exp.Before(time.Now().UTC().Add(50 * time.Minute)) {
		t.Fatalf("unexpected exp: %v", exp)
	}
	parts := strings.Split(tok, ".")
	if len(parts) != 3 {
		t.Fatalf("expected 3 jwt parts, got %d", len(parts))
	}
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(parts[0] + "." + parts[1]))
	if want := base64.RawURLEncoding.EncodeToString(mac.Sum(nil)); parts[2] != want {
		t.Fatalf("signature mismatch: got %q want %q", parts[2], want)
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatal(err)
	}
	var claims map[string]any
	if err := json.Unmarshal(raw, &claims); err != nil {
		t.Fatal(err)
	}
	if claims["sub"] != "user-123" {
		t.Fatalf("sub=%v", claims["sub"])
	}
	if _, hasChannel := claims["channel"]; hasChannel {
		t.Fatalf("connect token must not include channel claim: %v", claims)
	}

	subTok, _, err := SignCentrifugoToken(secret, "user-123", "chat:conv:abc", 5*time.Minute)
	if err != nil {
		t.Fatalf("subscription token: %v", err)
	}
	subRaw, err := base64.RawURLEncoding.DecodeString(strings.Split(subTok, ".")[1])
	if err != nil {
		t.Fatal(err)
	}
	var subClaims map[string]any
	if err := json.Unmarshal(subRaw, &subClaims); err != nil {
		t.Fatal(err)
	}
	if subClaims["channel"] != "chat:conv:abc" {
		t.Fatalf("channel=%v", subClaims["channel"])
	}
}
