package e2e

import (
	"context"
	"fmt"
	"github.com/google/uuid"
	temporalclient "go.temporal.io/sdk/client"
	"os"
	"strings"
	"testing"
	"time"
)

func TestDurableLifecycle(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, actor, ws := onboard(t, "user_lifecycle_"+suffix, "lifecycle-"+suffix+"@example.test", "019ad06b-7d00-7000-a100-"+suffix, 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	s, b = call(t, "POST", base+"/directories", map[string]any{"parent": map[string]string{"node_id": root}, "name": "purge-tree"}, h)
	requireStatus(t, s, 201, b)
	dir := jsonMap(t, b)["id"].(string)
	db := serviceDB(t, "letfs")
	ctx, cancel := context.WithTimeout(t.Context(), 60*time.Second)
	defer cancel()
	var fs, bucket string
	if e := db.QueryRow(ctx, "SELECT filesystem_id::text FROM nodes WHERE id=$1", root).Scan(&fs); e != nil {
		t.Fatal(e)
	}
	if e := db.QueryRow(ctx, "SELECT bucket_id::text FROM filesystems WHERE id=$1", fs).Scan(&bucket); e != nil {
		t.Fatal(e)
	}
	// A bounded set-based fixture crosses the 64-node transaction boundary.
	tx, e := db.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer tx.Rollback(context.Background())
	if _, e = tx.Exec(ctx, "WITH added AS (INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) SELECT uuidv7(),$1,$2,'file-'||i,'file',3 FROM generate_series(1,130) i RETURNING id) INSERT INTO file_data(node_id,storage_kind,inline_bytes) SELECT id,'inline',convert_to('abc','UTF8') FROM added", fs, dir); e != nil {
		t.Fatal(e)
	}
	if _, e = tx.Exec(ctx, "UPDATE filesystems SET node_count=node_count+130 WHERE id=$1", fs); e != nil {
		t.Fatal(e)
	}
	if _, e = tx.Exec(ctx, "UPDATE quota_buckets SET used_bytes=used_bytes+390 WHERE id=$1", bucket); e != nil {
		t.Fatal(e)
	}
	if _, e = tx.Exec(ctx, "UPDATE nodes SET revision=revision+130 WHERE id=$1", dir); e != nil {
		t.Fatal(e)
	}
	if e = tx.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	h["If-Match"] = "\"131\""
	s, b = call(t, "POST", base+"/trash", map[string]any{"locator": map[string]string{"node_id": dir}}, h)
	requireStatus(t, s, 200, b)
	trash := jsonMap(t, b)
	entry := trash["id"].(string)
	revision := trash["node"].(map[string]any)["revision"].(string)
	h["If-Match"] = "\"" + revision + "\""
	h["Idempotency-Key"] = uuid.NewString()
	s, b = call(t, "DELETE", base+"/trash/"+entry, nil, h)
	requireStatus(t, s, 202, b)
	op := jsonMap(t, b)
	waitOperation(t, op["status_url"].(string), h)
	saveHistory(t, "purge/"+fs+"/"+actor+"/"+h["Idempotency-Key"], "PurgeTrash")
	s, b = call(t, "DELETE", base+"/trash/"+entry, nil, h)
	requireStatus(t, s, 200, b)
	var used, nodes int64
	if e = db.QueryRow(ctx, "SELECT used_bytes FROM quota_buckets WHERE id=$1", bucket).Scan(&used); e != nil || used != 0 {
		t.Fatal("purge usage", used, e)
	}
	if e = db.QueryRow(ctx, "SELECT node_count FROM filesystems WHERE id=$1", fs).Scan(&nodes); e != nil || nodes != 1 {
		t.Fatal("purge count", nodes, e)
	}
	// Workspace deletion must include an extra filesystem in its shared bucket.
	secret, e := os.ReadFile("/run/secrets/workspace_service_token")
	if e != nil {
		t.Fatal(e)
	}
	ih := map[string]string{"Authorization": "Bearer " + strings.TrimSpace(string(secret))}
	extra, extraRoot := uuid.NewString(), uuid.NewString()
	s, b = call(t, "POST", "http://letfs:8080/internal/v1/filesystems/ensure", map[string]any{"id": extra, "bucket_id": bucket, "root_id": extraRoot, "provision_key": "lifecycle/" + extra, "root_name": "chat"}, ih)
	requireStatus(t, s, 200, b)
	// Register an unfinished upload and a published object before freezing the bucket.
	delete(h, "If-Match")
	delete(h, "Idempotency-Key")
	data := []byte{0, 1, 2}
	unfinished := prepareUpload(t, base, map[string]any{"parent": map[string]string{"node_id": root}, "name": "unfinished"}, data, "object", h)
	upload := unfinished["id"].(string)
	prepared := prepareUpload(t, base, map[string]any{"parent": map[string]string{"node_id": root}, "name": "binary"}, data, "object", h)
	binary := prepared["id"].(string)
	transferUpload(t, base, prepared, data, h)
	s, b = call(t, "POST", base+"/uploads/"+binary+"/finalize", nil, h)
	requireStatus(t, s, 200, b)
	h["If-Match"] = "\"1\""
	h["Idempotency-Key"] = uuid.NewString()
	s, b = call(t, "DELETE", "http://envoy:8080/v1/workspaces/"+ws, nil, h)
	requireStatus(t, s, 202, b)
	deletion := jsonMap(t, b)
	waitOperation(t, deletion["status_url"].(string), h)
	saveHistory(t, "delete-workspace/"+actor+"/"+h["Idempotency-Key"], "DeleteWorkspace")
	saveHistory(t, "delete-filesystem/"+fs+"/"+actor+"/"+deletion["operation_id"].(string), "DeleteFilesystem")
	s, b = call(t, "DELETE", "http://envoy:8080/v1/workspaces/"+ws, nil, h)
	requireStatus(t, s, 200, b)
	var state string
	if e = db.QueryRow(ctx, "SELECT state,used_bytes FROM quota_buckets WHERE id=$1", bucket).Scan(&state, &used); e != nil || state != "deleted" || used != 0 {
		t.Fatal("bucket tombstone", state, used, e)
	}
	if e = db.QueryRow(ctx, "SELECT count(*) FROM nodes WHERE filesystem_id=ANY($1::uuid[])", []string{fs, extra}).Scan(&nodes); e != nil || nodes != 0 {
		t.Fatal("filesystem nodes survived", nodes, e)
	}
	var deleted int
	if e = db.QueryRow(ctx, "SELECT count(*) FROM filesystems WHERE bucket_id=$1 AND state='deleted' AND root_id IS NULL AND node_count=0", bucket).Scan(&deleted); e != nil || deleted != 2 {
		t.Fatal("filesystem tombstones", deleted, e)
	}
	if e = db.QueryRow(ctx, "SELECT state FROM uploads WHERE id=$1", upload).Scan(&state); e != nil || state != "aborted" {
		t.Fatal("candidate survived", state, e)
	}
	s, b = call(t, "POST", "http://letfs:8080/internal/v1/filesystems/"+fs+"/files/uploads-finalize", map[string]any{"scope": map[string]any{"actor_id": actor, "mounts": []any{map[string]string{"path": "/drive", "filesystem_id": fs}}}, "input": map[string]string{"entry_id": upload}}, ih)
	requireStatus(t, s, 409, b)
	s, b = call(t, "POST", "http://letfs:8080/internal/v1/filesystems/ensure", map[string]any{"id": uuid.NewString(), "bucket_id": bucket, "root_id": uuid.NewString(), "provision_key": "late/" + extra, "root_name": "late"}, ih)
	requireStatus(t, s, 409, b)
	// Physical cleanup is separate; make the test's keys due and run the real finite workflow.
	if _, e = db.Exec(ctx, "UPDATE object_deletions SET eligible_at=now()-interval '1 second' WHERE bucket_id=$1", bucket); e != nil {
		t.Fatal(e)
	}
	tc, e := temporalclient.Dial(temporalclient.Options{HostPort: "temporal:7233", Namespace: "openlet"})
	if e != nil {
		t.Fatal(e)
	}
	defer tc.Close()
	run, e := tc.ExecuteWorkflow(ctx, temporalclient.StartWorkflowOptions{ID: "maintenance-test/" + suffix, TaskQueue: "openlet-letfs"}, "StorageMaintenance", nil)
	if e != nil {
		t.Fatal(e)
	}
	if e = run.Get(ctx, nil); e != nil {
		t.Fatal(e)
	}
	saveHistory(t, "maintenance-test/"+suffix, "StorageMaintenance")
	var pending int
	if e = db.QueryRow(ctx, "SELECT count(*) FROM object_deletions WHERE bucket_id=$1 AND state!='deleted'", bucket).Scan(&pending); e != nil || pending != 0 {
		t.Fatal("physical cleanup pending", pending, e)
	}
}

func TestStorageMaintenancePolicy(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, _, ws := onboard(t, "user_maintenance_"+suffix, "maintenance-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	parent := map[string]string{"node_id": root}
	s, b = call(t, "POST", base+"/text", map[string]any{"parent": parent, "name": "keep-trash", "text": "keep"}, h)
	requireStatus(t, s, 201, b)
	node := jsonMap(t, b)["id"].(string)
	h["If-Match"] = "\"1\""
	s, b = call(t, "POST", base+"/trash", map[string]any{"locator": map[string]string{"node_id": node}}, h)
	requireStatus(t, s, 200, b)
	entry := jsonMap(t, b)["id"].(string)
	delete(h, "If-Match")
	prepared := prepareUpload(t, base, map[string]any{"parent": parent, "name": "expired-candidate"}, []byte("pending"), "object", h)
	upload := prepared["id"].(string)
	db := serviceDB(t, "letfs")
	if _, e := db.Exec(t.Context(), "UPDATE uploads SET expires_at=now()-interval '1 day' WHERE id=$1", upload); e != nil {
		t.Fatal(e)
	}
	if _, e := db.Exec(t.Context(), "UPDATE trash_entries SET created_at=now()-interval '10 years' WHERE id=$1", entry); e != nil {
		t.Fatal(e)
	}
	tc, e := temporalclient.Dial(temporalclient.Options{HostPort: "temporal:7233", Namespace: "openlet"})
	if e != nil {
		t.Fatal(e)
	}
	defer tc.Close()
	run, e := tc.ExecuteWorkflow(t.Context(), temporalclient.StartWorkflowOptions{ID: "maintenance-policy/" + suffix, TaskQueue: "openlet-letfs"}, "StorageMaintenance", nil)
	if e != nil {
		t.Fatal(e)
	}
	if e = run.Get(t.Context(), nil); e != nil {
		t.Fatal(e)
	}
	var state string
	if e = db.QueryRow(t.Context(), "SELECT state FROM uploads WHERE id=$1", upload).Scan(&state); e != nil || state != "expired" {
		t.Fatal("expiry did not fence upload", state, e)
	}
	if e = db.QueryRow(t.Context(), "SELECT state FROM trash_entries WHERE id=$1", entry).Scan(&state); e != nil || state != "trashed" {
		t.Fatal("maintenance aged user trash", state, e)
	}
}

func TestRestorePurgeBarrier(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, _, ws := onboard(t, "user_purge_race_"+suffix, "purge-race-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	s, b = call(t, "POST", base+"/directories", map[string]any{"parent": map[string]string{"node_id": root}, "name": "race"}, h)
	requireStatus(t, s, 201, b)
	dir := jsonMap(t, b)["id"].(string)
	h["If-Match"] = "\"1\""
	s, b = call(t, "POST", base+"/trash", map[string]any{"locator": map[string]string{"node_id": dir}}, h)
	requireStatus(t, s, 200, b)
	entry := jsonMap(t, b)["id"].(string)
	h["If-Match"] = "\"2\""
	h["Idempotency-Key"] = uuid.NewString()
	db := serviceDB(t, "letfs")
	observer := serviceDB(t, "letfs")
	fs := filesystemForNode(t, root)
	ctx, cancel := context.WithTimeout(t.Context(), 20*time.Second)
	defer cancel()
	blocker, e := db.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer blocker.Rollback(context.Background())
	var bucket string
	if e = blocker.QueryRow(ctx, "SELECT id::text FROM quota_buckets WHERE id=(SELECT bucket_id FROM filesystems WHERE id=$1) FOR UPDATE", fs).Scan(&bucket); e != nil {
		t.Fatal(e)
	}
	type result struct {
		action string
		status int
		body   []byte
	}
	results := make(chan result, 2)
	go func() { s, b := call(t, "DELETE", base+"/trash/"+entry, nil, h); results <- result{"purge", s, b} }()
	go func() {
		s, b := call(t, "POST", base+"/trash/"+entry+"/restore", map[string]any{}, h)
		results <- result{"restore", s, b}
	}()
	for {
		var waiting int
		if e = observer.QueryRow(ctx, "SELECT count(*) FROM pg_stat_activity WHERE usename=current_user AND wait_event_type='Lock'").Scan(&waiting); e != nil {
			t.Fatal(e)
		}
		if waiting >= 2 {
			break
		}
		if ctx.Err() != nil {
			t.Fatal("purge/restore did not reach barrier")
		}
	}
	if e = blocker.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	statuses := map[string]int{}
	for i := 0; i < 2; i++ {
		r := <-results
		statuses[r.action] = r.status
		if r.action == "purge" && r.status == 202 {
			waitOperation(t, jsonMap(t, r.body)["status_url"].(string), h)
		}
	}
	if !((statuses["restore"] == 200 && statuses["purge"] == 404) || (statuses["purge"] == 202 && (statuses["restore"] == 409 || statuses["restore"] == 404))) {
		t.Fatal("inconsistent lifecycle winner", statuses)
	}
}
