package config

import (
	"errors"
	"net"
	"net/url"
	"strconv"
	"strings"
	"time"

	sharedconfig "github.com/qninhdt/openlet/packages/go/config"
)

type Config struct {
	Listen, RPCListen, RPCCertificatePath, RPCPrivateKeyPath, DatabaseURL, TemporalAddress, TemporalNamespace string
	GatewayToken, WorkspaceToken, AccountToken, AccountRPCAddress, LetfsRPCAddress                            string
	SpiceDBAddress, SpiceDBKey                                                                                string
	AllowPlaintextRPC                                                                                         bool
	MaxWorkspaces, MaxMembers                                                                                 int
	QuotaLimit                                                                                                int64
	InviteTTL                                                                                                 time.Duration
}

func Load() (Config, error) {
	return Parse(sharedconfig.Secret)
}
func Parse(get func(string) string) (Config, error) {
	c := Config{Listen: get("LISTEN_ADDR"), RPCListen: get("RPC_LISTEN_ADDR"), DatabaseURL: get("DATABASE_URL"), TemporalAddress: get("TEMPORAL_ADDRESS"), TemporalNamespace: get("TEMPORAL_NAMESPACE"), GatewayToken: get("GATEWAY_TOKEN"), WorkspaceToken: get("WORKSPACE_SERVICE_TOKEN"), AccountToken: get("ACCOUNT_SERVICE_TOKEN"), AccountRPCAddress: get("ACCOUNT_RPC_ADDRESS"), LetfsRPCAddress: get("LETFS_RPC_ADDRESS"), RPCCertificatePath: get("RPC_TLS_CERT_PATH"), RPCPrivateKeyPath: get("RPC_TLS_KEY_PATH")}
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
	if c.AllowPlaintextRPC {
		if c.RPCCertificatePath != "" || c.RPCPrivateKeyPath != "" {
			return c, errors.New("RPC TLS and plaintext configuration conflict")
		}
	} else if c.RPCCertificatePath == "" || c.RPCPrivateKeyPath == "" {
		return c, errors.New("RPC_TLS_CERT_PATH and RPC_TLS_KEY_PATH required for verified TLS")
	}
	c.SpiceDBAddress, c.SpiceDBKey = get("SPICEDB_ADDRESS"), get("SPICEDB_GRPC_PRESHARED_KEY")
	if host, port, err := net.SplitHostPort(c.SpiceDBAddress); err != nil || host == "" || port == "" {
		return c, errors.New("invalid SPICEDB_ADDRESS")
	}
	if host, port, err := net.SplitHostPort(c.AccountRPCAddress); err != nil || host == "" || port == "" {
		return c, errors.New("invalid ACCOUNT_RPC_ADDRESS")
	}
	if host, port, err := net.SplitHostPort(c.LetfsRPCAddress); err != nil || host == "" || port == "" {
		return c, errors.New("invalid LETFS_RPC_ADDRESS")
	}
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
	for _, t := range []string{c.GatewayToken, c.WorkspaceToken, c.AccountToken, c.SpiceDBKey} {
		if len(t) < 32 || strings.IndexFunc(t, func(r rune) bool {
			return !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '-' || r == '_')
		}) >= 0 {
			return c, errors.New("invalid service token")
		}
	}
	return c, nil
}
