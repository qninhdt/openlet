package sdk

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"time"
)

const jwtHS256Header = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"

// SignCentrifugoToken signs an HS256 JWT for Centrifugo v6 connection (channel == "")
// or channel subscription (channel != "") using only the Go standard library.
func SignCentrifugoToken(secret, userID, channel string, ttl time.Duration) (string, time.Time, error) {
	if secret == "" {
		return "", time.Time{}, fmt.Errorf("centrifugo token secret is required")
	}
	if userID == "" {
		return "", time.Time{}, fmt.Errorf("user_id is required")
	}
	if ttl <= 0 {
		ttl = time.Hour
	}
	exp := time.Now().UTC().Add(ttl)
	claims := map[string]any{
		"sub": userID,
		"exp": exp.Unix(),
	}
	if channel != "" {
		claims["channel"] = channel
	}
	payload, err := json.Marshal(claims)
	if err != nil {
		return "", time.Time{}, err
	}
	signingInput := jwtHS256Header + "." + base64.RawURLEncoding.EncodeToString(payload)
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(signingInput))
	sig := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	return signingInput + "." + sig, exp, nil
}
