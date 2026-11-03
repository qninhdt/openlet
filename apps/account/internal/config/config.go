package config

import (
	"errors"
	"net"
	"net/url"
	"strings"

	sharedconfig "openlet/packages/go/config"
)

type Config struct {
	Listen, RPCListen, RPCCertificatePath, RPCPrivateKeyPath                                             string
	DatabaseURL, TemporalAddress, TemporalNamespace, GatewayToken, WorkspaceToken, ClerkURL, ClerkSecret string
	SpiceDBAddress, SpiceDBKey                                                                           string
	AllowPlaintextRPC                                                                                    bool
}

func Load() (Config, error) {
	return Parse(sharedconfig.Secret)
}
func Parse(get func(string) string) (Config, error) {
	c := Config{Listen: get("LISTEN_ADDR"), DatabaseURL: get("DATABASE_URL"), TemporalAddress: get("TEMPORAL_ADDRESS"), TemporalNamespace: get("TEMPORAL_NAMESPACE"), GatewayToken: get("GATEWAY_TOKEN"), WorkspaceToken: get("WORKSPACE_SERVICE_TOKEN")}
	c.RPCListen = get("RPC_LISTEN_ADDR")
	if c.RPCListen == "" {
		c.RPCListen = ":9090"
	}
	if _, _, err := net.SplitHostPort(c.RPCListen); err != nil {
		return c, errors.New("invalid RPC_LISTEN_ADDR")
	}
	plaintext := get("ALLOW_PLAINTEXT_RPC")
	if plaintext != "" && plaintext != "false" && plaintext != "true" {
		return c, errors.New("ALLOW_PLAINTEXT_RPC must be true or false")
	}
	c.AllowPlaintextRPC = plaintext == "true"
	c.SpiceDBAddress, c.SpiceDBKey = get("SPICEDB_ADDRESS"), get("SPICEDB_GRPC_PRESHARED_KEY")
	if host, port, err := net.SplitHostPort(c.SpiceDBAddress); err != nil || host == "" || port == "" {
		return c, errors.New("invalid SPICEDB_ADDRESS")
	}
	c.RPCCertificatePath, c.RPCPrivateKeyPath = get("RPC_TLS_CERT_PATH"), get("RPC_TLS_KEY_PATH")
	if c.AllowPlaintextRPC {
		if c.RPCCertificatePath != "" || c.RPCPrivateKeyPath != "" {
			return c, errors.New("RPC TLS and plaintext configuration conflict")
		}
	} else if c.RPCCertificatePath == "" || c.RPCPrivateKeyPath == "" {
		return c, errors.New("RPC_TLS_CERT_PATH and RPC_TLS_KEY_PATH required for verified TLS")
	}
	c.ClerkURL = get("CLERK_API_URL")
	if c.ClerkURL == "" {
		c.ClerkURL = "https://api.clerk.com/v1"
	}
	c.ClerkSecret = get("CLERK_SECRET_KEY")
	if c.ClerkSecret == "" || strings.ContainsAny(c.ClerkSecret, "\r\n") {
		return c, errors.New("CLERK_SECRET_KEY required")
	}
	clerkURL, clerkErr := url.Parse(c.ClerkURL)
	if clerkErr != nil || clerkURL.Host == "" || clerkURL.User != nil || (clerkURL.Scheme != "https" && !(get("ALLOW_TEST_HTTP") == "true" && clerkURL.Scheme == "http")) {
		return c, errors.New("invalid CLERK_API_URL")
	}
	if c.Listen == "" {
		c.Listen = ":8080"
	}
	if _, _, e := net.SplitHostPort(c.Listen); e != nil {
		return c, errors.New("invalid LISTEN_ADDR")
	}
	u, e := url.Parse(c.DatabaseURL)
	if e != nil || u.Host == "" || u.User == nil || (u.Scheme != "postgres" && u.Scheme != "postgresql") {
		return c, errors.New("invalid DATABASE_URL")
	}
	if pw, ok := u.User.Password(); !ok || pw == "" {
		return c, errors.New("DATABASE_URL password required")
	}
	if _, _, e = net.SplitHostPort(c.TemporalAddress); e != nil || c.TemporalNamespace == "" {
		return c, errors.New("invalid Temporal address or namespace")
	}
	for _, t := range []string{c.GatewayToken, c.WorkspaceToken, c.SpiceDBKey} {
		if len(t) < 32 || strings.IndexFunc(t, func(r rune) bool {
			return !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_')
		}) >= 0 {
			return c, errors.New("invalid service token")
		}
	}
	return c, nil
}
