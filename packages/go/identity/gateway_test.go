package identity

import (
	"net/http"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func TestGatewayUserAndSubjectOnlyBootstrap(t *testing.T) {
	const token = "isolated-verified-gateway-token-12345"
	const actor = "019a3b66-0000-7000-8000-000000000001"
	for _, test := range []struct {
		name      string
		bootstrap bool
		change    func(http.Header)
		err       error
	}{
		{"user", false, nil, nil},
		{"bootstrap", true, func(h http.Header) { h.Del("X-Openlet-User-ID") }, nil},
		{"bootstrap ignores actor", true, func(h http.Header) { h.Set("X-Openlet-User-ID", "untrusted") }, nil},
		{"missing credential", false, func(h http.Header) { h.Del("X-Gateway-Token") }, ErrGatewayCredential},
		{"wrong credential", false, func(h http.Header) { h.Set("X-Gateway-Token", "other") }, ErrGatewayCredential},
		{"duplicate credential", true, func(h http.Header) { h.Add("X-Gateway-Token", token) }, ErrGatewayCredential},
		{"missing subject", false, func(h http.Header) { h.Del("X-Clerk-Sub") }, ErrGatewaySubject},
		{"empty subject", true, func(h http.Header) { h.Set("X-Clerk-Sub", "") }, ErrGatewaySubject},
		{"duplicate subject", true, func(h http.Header) { h.Add("X-Clerk-Sub", "user_other") }, ErrGatewaySubject},
		{"missing actor", false, func(h http.Header) { h.Del("X-Openlet-User-ID") }, ErrOnboardingRequired},
		{"invalid actor", false, func(h http.Header) { h.Set("X-Openlet-User-ID", "untrusted") }, ErrOnboardingRequired},
		{"nil actor", false, func(h http.Header) { h.Set("X-Openlet-User-ID", uuid.Nil.String()) }, ErrOnboardingRequired},
		{"duplicate actor", false, func(h http.Header) { h.Add("X-Openlet-User-ID", actor) }, ErrOnboardingRequired},
		{"duplicate bootstrap actor", true, func(h http.Header) { h.Add("X-Openlet-User-ID", actor) }, ErrOnboardingRequired},
	} {
		t.Run(test.name, func(t *testing.T) {
			headers := http.Header{}
			headers.Set("X-Gateway-Token", token)
			headers.Set("X-Clerk-Sub", "user_test")
			headers.Set("X-Openlet-User-ID", actor)
			if test.change != nil {
				test.change(headers)
			}
			principal, err := AuthenticateGateway(headers, token, test.bootstrap)
			require.ErrorIs(t, err, test.err)
			if err != nil {
				require.Equal(t, Principal{}, principal)
				return
			}
			require.True(t, principal.Gateway)
			require.Equal(t, "gateway", principal.Service)
			require.Equal(t, "user_test", principal.Subject)
			if test.bootstrap {
				require.Equal(t, uuid.Nil, principal.ActorID)
			} else {
				require.Equal(t, actor, principal.ActorID.String())
			}
		})
	}
	headers := http.Header{"X-Gateway-Token": {""}, "X-Clerk-Sub": {"user_test"}}
	_, err := AuthenticateGateway(headers, "", true)
	require.ErrorIs(t, err, ErrGatewayCredential)
}
