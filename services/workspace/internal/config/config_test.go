package config

import (
	"strings"
	"testing"
)

func TestConfigValidation(t *testing.T) {
	good := map[string]string{"DATABASE_URL": "postgres://u:p@postgres/db", "TEMPORAL_ADDRESS": "temporal:7233", "TEMPORAL_NAMESPACE": "openlet", "GATEWAY_TOKEN": strings.Repeat("a", 43), "USER_SERVICE_TOKEN": strings.Repeat("b", 43), "WORKSPACE_SERVICE_TOKEN": strings.Repeat("c", 43), "USER_URL": "http://user:8080", "LETFS_URL": "http://letfs:8080"}
	get := func(k string) string { return good[k] }
	if _, e := Parse(get); e != nil {
		t.Fatal(e)
	}
	for _, key := range []string{"DATABASE_URL", "TEMPORAL_ADDRESS", "TEMPORAL_NAMESPACE", "GATEWAY_TOKEN", "USER_URL", "LETFS_URL"} {
		v := good[key]
		good[key] = ""
		if _, e := Parse(get); e == nil {
			t.Errorf("accepted missing %s", key)
		}
		good[key] = v
	}
}
