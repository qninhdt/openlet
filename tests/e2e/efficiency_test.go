package e2e

import (
	"fmt"
	"github.com/google/uuid"
	"testing"
	"time"
)

func TestFilesystemEfficiency(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, _, ws := onboard(t, "user_efficiency_"+suffix, "efficiency-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	db := serviceDB(t, "letfs")
	// The counter comes from PostgreSQL, not a mock repository or the handler implementation.
	count := func(pattern string) int64 {
		var n int64
		if e := db.QueryRow(t.Context(), "SELECT coalesce(sum(calls),0)::bigint FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database()) AND query LIKE $1", pattern).Scan(&n); e != nil {
			t.Fatal(e)
		}
		return n
	}
	for _, n := range []int{1, 100} {
		locators := make([]any, n)
		for i := range locators {
			locators[i] = map[string]string{"path": "/drive", "expected_node_id": root}
		}
		before := count("WITH RECURSIVE%")
		s, b = call(t, "POST", base+"/batch-stat", map[string]any{"locators": locators}, h)
		requireStatus(t, s, 200, b)
		if got := count("WITH RECURSIVE%") - before; got != 1 {
			t.Fatalf("batch of %d used %d path statements", n, got)
		}
	}
	for _, n := range []int{1, 100} {
		before := count("SELECT * FROM nodes WHERE filesystem_id%")
		s, b = call(t, "GET", fmt.Sprintf("%s/list?node_id=%s&limit=%d", base, root, n), nil, h)
		requireStatus(t, s, 200, b)
		if got := count("SELECT * FROM nodes WHERE filesystem_id%") - before; got != 1 {
			t.Fatalf("list limit %d used %d page statements", n, got)
		}
	}
}
