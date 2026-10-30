package config

import (
	"errors"
	"net"
	"net/url"
	"os"
	"strings"
)

type Config struct{ Listen, DatabaseURL, TemporalAddress, TemporalNamespace, GatewayToken, UserToken, WorkspaceToken, WorkspaceURL, ClerkURL, ClerkSecret string }

func Load() (Config, error) {
	return Parse(func(k string) string {
		if p := os.Getenv(k + "_FILE"); p != "" {
			b, e := os.ReadFile(p)
			if e != nil {
				return ""
			}
			return strings.TrimSpace(string(b))
		}
		return os.Getenv(k)
	})
}
func Parse(get func(string) string) (Config, error) {
	c := Config{Listen: get("LISTEN_ADDR"), DatabaseURL: get("DATABASE_URL"), TemporalAddress: get("TEMPORAL_ADDRESS"), TemporalNamespace: get("TEMPORAL_NAMESPACE"), GatewayToken: get("GATEWAY_TOKEN"), UserToken: get("USER_SERVICE_TOKEN"), WorkspaceToken: get("WORKSPACE_SERVICE_TOKEN"), WorkspaceURL: get("WORKSPACE_URL")}
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
	for _, t := range []string{c.GatewayToken, c.UserToken, c.WorkspaceToken} {
		if len(t) < 32 || strings.IndexFunc(t, func(r rune) bool {
			return !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_')
		}) >= 0 {
			return c, errors.New("invalid service token")
		}
	}
	u, e = url.Parse(c.WorkspaceURL)
	if e != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") {
		return c, errors.New("invalid service URL")
	}
	return c, nil
}
