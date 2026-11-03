package config

import (
	"strings"
	"testing"
)

func TestConfigValidation(t *testing.T) {
	good := map[string]string{"SPICEDB_ADDRESS": "spicedb:50051", "SPICEDB_GRPC_PRESHARED_KEY": strings.Repeat("s", 43), "ALLOW_PLAINTEXT_RPC": "true", "CLERK_SECRET_KEY": "test-key", "DATABASE_URL": "postgres://u:p@postgres/db", "TEMPORAL_ADDRESS": "temporal:7233", "TEMPORAL_NAMESPACE": "openlet", "GATEWAY_TOKEN": strings.Repeat("a", 43), "WORKSPACE_SERVICE_TOKEN": strings.Repeat("c", 43), "ACCOUNT_SERVICE_TOKEN": strings.Repeat("d", 43), "WORKSPACE_RPC_ADDRESS": "workspace:9090"}
	get := func(k string) string { return good[k] }
	if _, e := Parse(get); e != nil {
		t.Fatal(e)
	}
	for _, key := range []string{"SPICEDB_ADDRESS", "SPICEDB_GRPC_PRESHARED_KEY", "DATABASE_URL", "TEMPORAL_ADDRESS", "TEMPORAL_NAMESPACE", "GATEWAY_TOKEN"} {
		v := good[key]
		good[key] = ""
		if _, e := Parse(get); e == nil {
			t.Errorf("accepted missing %s", key)
		}
		good[key] = v
	}
}

func TestRPCTransportRequiresExplicitLocalPlaintextOrTLS(t *testing.T) {
	good := map[string]string{"SPICEDB_ADDRESS": "spicedb:50051", "SPICEDB_GRPC_PRESHARED_KEY": strings.Repeat("s", 43), "CLERK_SECRET_KEY": "test-key", "DATABASE_URL": "postgres://u:p@postgres/db", "TEMPORAL_ADDRESS": "temporal:7233", "TEMPORAL_NAMESPACE": "openlet", "GATEWAY_TOKEN": strings.Repeat("a", 43), "WORKSPACE_SERVICE_TOKEN": strings.Repeat("c", 43), "ACCOUNT_SERVICE_TOKEN": strings.Repeat("d", 43), "WORKSPACE_RPC_ADDRESS": "workspace:9090"}
	get := func(key string) string { return good[key] }
	if _, err := Parse(get); err == nil {
		t.Fatal("accepted missing server TLS credentials")
	}
	good["RPC_TLS_CERT_PATH"], good["RPC_TLS_KEY_PATH"] = "/certs/certificate", "/certs/private-key"
	if config, err := Parse(get); err != nil || config.AllowPlaintextRPC || config.RPCListen != ":9090" {
		t.Fatalf("verified TLS configuration rejected: %v", err)
	}
	good["ALLOW_PLAINTEXT_RPC"] = "true"
	if _, err := Parse(get); err == nil {
		t.Fatal("accepted conflicting TLS and plaintext")
	}
	delete(good, "RPC_TLS_CERT_PATH")
	delete(good, "RPC_TLS_KEY_PATH")
	for key, value := range map[string]string{"ALLOW_PLAINTEXT_RPC": "yes", "RPC_LISTEN_ADDR": "bad-address"} {
		previous := good[key]
		good[key] = value
		if _, err := Parse(get); err == nil {
			t.Fatalf("accepted invalid %s", key)
		}
		good[key] = previous
	}
}
