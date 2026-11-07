package identity

import (
	"crypto/subtle"
	"errors"
	"net/http"

	"github.com/google/uuid"
)

var (
	ErrGatewayCredential  = errors.New("gateway authentication required")
	ErrGatewaySubject     = errors.New("verified subject required")
	ErrOnboardingRequired = errors.New("refresh an onboarded session")
)

// The owner enables subject-only bootstrap on its exact onboarding routes.
func AuthenticateGateway(headers http.Header, token string, bootstrap bool) (Principal, error) {
	if token == "" || len(headers.Values("X-Gateway-Token")) != 1 ||
		subtle.ConstantTimeCompare([]byte(headers.Get("X-Gateway-Token")), []byte(token)) != 1 {
		return Principal{}, ErrGatewayCredential
	}
	if len(headers.Values("X-Clerk-Sub")) != 1 || headers.Get("X-Clerk-Sub") == "" {
		return Principal{}, ErrGatewaySubject
	}
	principal := Principal{Service: "gateway", Subject: headers.Get("X-Clerk-Sub"), Gateway: true}
	actors := headers.Values("X-Openlet-Account-ID")
	if len(actors) > 1 {
		return Principal{}, ErrOnboardingRequired
	}
	if bootstrap {
		return principal, nil
	}
	if len(actors) != 1 {
		return Principal{}, ErrOnboardingRequired
	}
	actor, err := uuid.Parse(actors[0])
	if err != nil || actor == uuid.Nil {
		return Principal{}, ErrOnboardingRequired
	}
	principal.ActorID = actor
	return principal, nil
}
