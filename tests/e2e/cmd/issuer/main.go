package main

import (
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"log"
	"math/big"
	"net/http"
	"time"
)

func main() {
	key, e := rsa.GenerateKey(rand.Reader, 2048)
	if e != nil {
		log.Fatal(e)
	}
	other, e := rsa.GenerateKey(rand.Reader, 2048)
	if e != nil {
		log.Fatal(e)
	}
	mux := http.NewServeMux()
	clerkRoutes(mux)
	storageRoutes(mux)
	enc := base64.RawURLEncoding.EncodeToString
	mux.HandleFunc("GET /.well-known/jwks.json", func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]any{"keys": []any{map[string]string{"kty": "RSA", "kid": "test", "use": "sig", "alg": "RS256", "n": enc(key.N.Bytes()), "e": enc(big.NewInt(int64(key.E)).Bytes())}}})
	})
	mux.HandleFunc("POST /token", func(w http.ResponseWriter, r *http.Request) {
		var in struct {
			Claims       map[string]any `json:"claims"`
			BadSignature bool           `json:"bad_signature"`
		}
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 8192)).Decode(&in) != nil {
			w.WriteHeader(400)
			return
		}
		claims := map[string]any{"iss": "http://issuer:8080", "aud": "openlet-test", "sub": "user_test", "iat": time.Now().Unix(), "exp": time.Now().Add(time.Hour).Unix(), "openlet_user_id": "019ad06b-7d00-7000-8000-000000000001"}
		for k, v := range in.Claims {
			if v == nil {
				delete(claims, k)
			} else {
				claims[k] = v
			}
		}
		h, _ := json.Marshal(map[string]string{"alg": "RS256", "kid": "test", "typ": "JWT"})
		b, _ := json.Marshal(claims)
		unsigned := enc(h) + "." + enc(b)
		digest := sha256.Sum256([]byte(unsigned))
		signing := key
		if in.BadSignature {
			signing = other
		}
		signature, e := rsa.SignPKCS1v15(rand.Reader, signing, crypto.SHA256, digest[:])
		if e != nil {
			w.WriteHeader(500)
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		_ = json.NewEncoder(w).Encode(map[string]string{"token": unsigned + "." + enc(signature)})
	})
	log.Fatal((&http.Server{Addr: ":8080", Handler: mux, ReadHeaderTimeout: 5 * time.Second}).ListenAndServe())
}
