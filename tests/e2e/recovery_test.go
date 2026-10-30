package e2e

import (
	"context"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	temporalclient "go.temporal.io/sdk/client"
)

func TestAdmissionReplacement(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Second)
	defer cancel()
	tc, e := temporalclient.Dial(temporalclient.Options{HostPort: "temporal:7233", Namespace: "openlet"})
	if e != nil {
		t.Fatal(e)
	}
	defer tc.Close()
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, actor, _ := onboard(t, "user_admission_"+suffix, "admission-"+suffix+"@example.test", "019ad06b-7d00-7000-9100-"+suffix, 0)
	for i := 0; i < 2; i++ {
		key := uuid.NewString()
		id := "create-workspace/" + actor + "/" + key
		original := map[string]string{"actor_id": actor, "request_key": key, "workspace_id": uuid.Nil.String(), "name": "replacement"}
		run, e := tc.ExecuteWorkflow(ctx, temporalclient.StartWorkflowOptions{ID: id, TaskQueue: "openlet-offline", WorkflowExecutionTimeout: time.Second}, "CreateWorkspace", original)
		if e != nil {
			t.Fatal(e)
		}
		if run.Get(ctx, nil) == nil {
			t.Fatal("offline run unexpectedly succeeded")
		}
		name := "replacement"
		want := 202
		if i == 1 {
			name = "conflicting"
			want = 409
		}
		s, b := call(t, "POST", "http://envoy:8080/v1/workspaces", map[string]string{"name": name}, map[string]string{"Authorization": "Bearer " + jwt, "Idempotency-Key": key})
		requireStatus(t, s, want, b)
	}
}
func workspaceDB(t *testing.T) *pgx.Conn { return serviceDB(t, "workspace") }
func serviceDB(t *testing.T, service string) *pgx.Conn {
	t.Helper()
	b, e := os.ReadFile("/run/secrets/" + service + "_database_url")
	if e != nil {
		t.Fatal(e)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	db, e := pgx.Connect(ctx, strings.TrimSpace(string(b)))
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { _ = db.Close(context.Background()) })
	return db
}
func TestOwnershipLockRechecks(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, owner, ws := onboard(t, "user_lock_owner_"+suffix, "lock-owner-"+suffix+"@example.test", "019ad06b-7d00-7000-9200-"+suffix, 0)
	target := uuid.NewString()
	db := workspaceDB(t)
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	_, e := db.Exec(ctx, "INSERT INTO workspace_members(workspace_id,user_id,role) VALUES($1,$2,'editor')", ws, target)
	if e != nil {
		t.Fatal(e)
	}
	blocker, e := db.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer blocker.Rollback(context.Background())
	var pid int
	var id string
	if e = blocker.QueryRow(ctx, "SELECT pg_backend_pid(),id::text FROM workspaces WHERE id=$1 FOR UPDATE", ws).Scan(&pid, &id); e != nil {
		t.Fatal(e)
	}
	result := make(chan int, 1)
	go func() {
		s, _ := call(t, "POST", "http://envoy:8080/v1/workspaces/"+ws+"/ownership", map[string]string{"user_id": target}, map[string]string{"Authorization": "Bearer " + jwt})
		result <- s
	}()
	observer := workspaceDB(t)
	// The lock graph is the barrier: do not commit the competing transfer until the API is waiting.
	for {
		var blocked bool
		if e = observer.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE $1=ANY(pg_blocking_pids(pid)))", pid).Scan(&blocked); e != nil {
			t.Fatal(e)
		}
		if blocked {
			break
		}
		select {
		case s := <-result:
			t.Fatalf("request bypassed workspace lock: %d", s)
		case <-ctx.Done():
			t.Fatal("API did not reach lock barrier")
		default:
		}
	}
	if _, e = blocker.Exec(ctx, "UPDATE workspace_members SET role='editor' WHERE workspace_id=$1 AND user_id=$2", ws, owner); e != nil {
		t.Fatal(e)
	}
	if _, e = blocker.Exec(ctx, "UPDATE workspace_members SET role='owner' WHERE workspace_id=$1 AND user_id=$2", ws, target); e != nil {
		t.Fatal(e)
	}
	if e = blocker.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	select {
	case status := <-result:
		if status != 403 {
			t.Fatalf("stale Owner authorized after lock: %d", status)
		}
	case <-ctx.Done():
		t.Fatal(ctx.Err())
	}
	var owners int
	if e = db.QueryRow(ctx, "SELECT count(*) FROM workspace_members WHERE workspace_id=$1 AND role='owner'", ws).Scan(&owners); e != nil || owners != 1 {
		t.Fatal("Owner invariant", owners, e)
	}
}

func TestLetfsAdmissionReplacement(t *testing.T) {
	tc, e := temporalclient.Dial(temporalclient.Options{HostPort: "temporal:7233", Namespace: "openlet"})
	if e != nil {
		t.Fatal(e)
	}
	defer tc.Close()
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, actor, ws := onboard(t, "user_fs_admit_"+suffix, "fs-admit-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	fs := filesystemForNode(t, root)
	parent := map[string]string{"node_id": root}
	s, b = call(t, "POST", base+"/directories", map[string]any{"parent": parent, "name": "admission-source"}, h)
	requireStatus(t, s, 201, b)
	dir := jsonMap(t, b)["id"].(string)
	key := uuid.NewString()
	input := map[string]any{"locator": map[string]string{"node_id": dir}, "parent": parent, "name": "admission-copy", "revision": "1", "request_key": key}
	start := map[string]any{"filesystem_id": fs, "request": map[string]any{"scope": map[string]any{"actor_id": actor, "mounts": []any{map[string]string{"path": "/drive", "filesystem_id": fs}}}, "input": input}}
	argument := map[string]any{"operation_id": nil, "start": start}
	ctx, cancel := context.WithTimeout(t.Context(), 40*time.Second)
	defer cancel()
	id := "copy/" + fs + "/" + actor + "/" + key
	run, e := tc.ExecuteWorkflow(ctx, temporalclient.StartWorkflowOptions{ID: id, TaskQueue: "openlet-offline", WorkflowExecutionTimeout: time.Second}, "CopyNode", argument)
	if e != nil {
		t.Fatal(e)
	}
	if run.Get(ctx, nil) == nil {
		t.Fatal("offline workflow succeeded")
	}
	h["If-Match"] = "\"1\""
	h["Idempotency-Key"] = key
	s, b = call(t, "POST", base+"/copy", map[string]any{"locator": map[string]string{"node_id": dir}, "parent": parent, "name": "wrong-input"}, h)
	requireStatus(t, s, 409, b)
	s, b = call(t, "POST", base+"/copy", map[string]any{"locator": map[string]string{"node_id": dir}, "parent": parent, "name": "admission-copy"}, h)
	requireStatus(t, s, 202, b)
	waitFileOperation(t, jsonMap(t, b)["status_url"].(string), h)
	// A separate owner-local DeleteFilesystem run also replaces a closed pre-admission run.
	token, e := os.ReadFile("/run/secrets/workspace_service_token")
	if e != nil {
		t.Fatal(e)
	}
	ih := map[string]string{"Authorization": "Bearer " + strings.TrimSpace(string(token))}
	db := serviceDB(t, "letfs")
	var bucket string
	if e = db.QueryRow(ctx, "SELECT bucket_id::text FROM filesystems WHERE id=$1", fs).Scan(&bucket); e != nil {
		t.Fatal(e)
	}
	extra := uuid.NewString()
	extraRoot := uuid.NewString()
	key = uuid.NewString()
	s, b = call(t, "POST", "http://letfs:8080/internal/v1/filesystems/ensure", map[string]any{"id": extra, "bucket_id": bucket, "root_id": extraRoot, "provision_key": "admission/" + extra, "root_name": "temporary"}, ih)
	requireStatus(t, s, 200, b)
	deletion := map[string]any{"filesystem_id": extra, "actor_id": actor, "request_key": key, "entry_id": nil, "revision": nil}
	argument = map[string]any{"operation_id": nil, "start": deletion}
	id = "delete-filesystem/" + extra + "/" + actor + "/" + key
	run, e = tc.ExecuteWorkflow(ctx, temporalclient.StartWorkflowOptions{ID: id, TaskQueue: "openlet-offline", WorkflowExecutionTimeout: time.Second}, "DeleteFilesystem", argument)
	if e != nil {
		t.Fatal(e)
	}
	if run.Get(ctx, nil) == nil {
		t.Fatal("offline workflow succeeded")
	}
	s, b = call(t, "POST", "http://letfs:8080/internal/v1/filesystems/"+extra+"/delete", deletion, ih)
	requireStatus(t, s, 202, b)
	if e = tc.GetWorkflow(ctx, id, "").Get(ctx, nil); e != nil {
		t.Fatal(e)
	}
}
