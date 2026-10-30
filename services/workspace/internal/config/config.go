package config

import (
	"errors"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
)

type Config struct {
	Listen, DatabaseURL, TemporalAddress, TemporalNamespace, GatewayToken, UserToken, WorkspaceToken, UserURL, LetfsURL string
	MaxWorkspaces, MaxMembers                                                                                           int
	QuotaLimit                                                                                                          int64
	InviteTTL                                                                                                           time.Duration
}

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
	c := Config{Listen: get("LISTEN_ADDR"), DatabaseURL: get("DATABASE_URL"), TemporalAddress: get("TEMPORAL_ADDRESS"), TemporalNamespace: get("TEMPORAL_NAMESPACE"), GatewayToken: get("GATEWAY_TOKEN"), UserToken: get("USER_SERVICE_TOKEN"), WorkspaceToken: get("WORKSPACE_SERVICE_TOKEN"), UserURL: get("USER_URL"), LetfsURL: get("LETFS_URL")}
	c.MaxWorkspaces = 100
	c.MaxMembers = 100
	c.QuotaLimit = 10737418240
	c.InviteTTL = 7 * 24 * time.Hour
	for key, target := range map[string]*int{"MAX_OWNED_WORKSPACES": &c.MaxWorkspaces, "MAX_MEMBERS": &c.MaxMembers} {
		if value := get(key); value != "" {
			parsed, e := strconv.Atoi(value)
			if e != nil || parsed <= 0 {
				return c, errors.New("invalid workspace policy limit")
			}
			*target = parsed
		}
	}
	if value := get("DEFAULT_QUOTA_BYTES"); value != "" {
		parsed, e := strconv.ParseInt(value, 10, 64)
		if e != nil || parsed < 0 {
			return c, errors.New("invalid DEFAULT_QUOTA_BYTES")
		}
		c.QuotaLimit = parsed
	}
	if value := get("INVITE_TTL"); value != "" {
		parsed, e := time.ParseDuration(value)
		if e != nil || parsed <= 0 {
			return c, errors.New("invalid INVITE_TTL")
		}
		c.InviteTTL = parsed
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
	for _, s := range []string{c.UserURL, c.LetfsURL} {
		u, e := url.Parse(s)
		if e != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") {
			return c, errors.New("invalid service URL")
		}
	}
	return c, nil
}
