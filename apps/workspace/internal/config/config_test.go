package config

import (
	"strings"
	"testing"
)

func TestConfigValidation(t *testing.T) {
	good := map[string]string{"SPICEDB_ADDRESS": "spicedb:50051", "SPICEDB_GRPC_PRESHARED_KEY": strings.Repeat("s", 43), "DATABASE_URL": "postgres://u:p@postgres/db", "TEMPORAL_ADDRESS": "temporal:7233", "TEMPORAL_NAMESPACE": "openlet", "GATEWAY_TOKEN": strings.Repeat("a", 43), "WORKSPACE_SERVICE_TOKEN": strings.Repeat("c", 43), "ACCOUNT_RPC_ADDRESS": "account:9090"}
	get := func(k string) string { return good[k] }
	if _, e := Parse(get); e != nil {
		t.Fatal(e)
	}
	for _, key := range []string{"SPICEDB_ADDRESS", "SPICEDB_GRPC_PRESHARED_KEY", "DATABASE_URL", "TEMPORAL_ADDRESS", "TEMPORAL_NAMESPACE", "GATEWAY_TOKEN", "ACCOUNT_RPC_ADDRESS"} {
		v := good[key]
		good[key] = ""
		if _, e := Parse(get); e == nil {
			t.Errorf("accepted missing %s", key)
		}
		good[key] = v
	}
}
