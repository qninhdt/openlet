package e2e

import (
	"context"
	"fmt"
	"net/url"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestFilesystemCore(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	owner, _, ws := onboard(t, "user_files_"+suffix, "files-"+suffix+"@example.test", "019ad06b-7d00-7000-8300-"+suffix, 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + owner}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	parent := map[string]string{"path": "/drive", "expected_parent_id": root}
	s, b = call(t, "POST", base+"/directories", map[string]any{"parent": parent, "name": "folder"}, h)
	requireStatus(t, s, 201, b)
	folder := jsonMap(t, b)["id"].(string)
	exact := "\ufeffViệt\r\n\n"
	s, b = call(t, "POST", base+"/text", map[string]any{"parent": parent, "name": "a.txt", "text": exact}, h)
	requireStatus(t, s, 201, b)
	node := jsonMap(t, b)
	id := node["id"].(string)
	s, b = call(t, "GET", base+"/stat?path="+url.QueryEscape("/drive/a.txt/."), nil, h)
	requireStatus(t, s, 200, b)
	s, b = call(t, "POST", base+"/uploads", map[string]any{"parent": parent, "name": "invalid-upload", "text": "unexpected body"}, h)
	requireStatus(t, s, 400, b)
	s, b = call(t, "GET", base+"/content?node_id="+id, nil, h)
	requireStatus(t, s, 200, b)
	if string(b) != exact {
		t.Fatal("text bytes changed")
	}
	h["Range"] = "bytes=0-2"
	s, b = call(t, "GET", base+"/content?node_id="+id, nil, h)
	requireStatus(t, s, 206, b)
	if string(b) != exact[:3] {
		t.Fatal("range mismatch")
	}
	delete(h, "Range")
	s, b = call(t, "GET", base+"/stat?path="+url.QueryEscape("/drive/../drive"), nil, h)
	requireStatus(t, s, 404, b)
	s, b = call(t, "POST", base+"/batch-stat", map[string]any{"locators": []any{map[string]string{"path": "/drive/a.txt"}, map[string]string{"node_id": folder}}}, h)
	requireStatus(t, s, 200, b)
	if len(jsonMap(t, b)["items"].([]any)) != 2 {
		t.Fatal("batch size")
	}
	h["If-Match"] = "\"1\""
	s, b = call(t, "PUT", base+"/text", map[string]any{"locator": map[string]string{"path": "/drive/a.txt", "expected_node_id": folder}, "text": "wrong"}, h)
	requireStatus(t, s, 412, b)
	s, b = call(t, "PUT", base+"/text", map[string]any{"locator": map[string]string{"node_id": id}, "text": "updated"}, h)
	requireStatus(t, s, 200, b)
	s, b = call(t, "POST", base+"/trash", map[string]any{"locator": map[string]string{"node_id": id}}, h)
	requireStatus(t, s, 412, b)
	h["If-Match"] = "\"2\""
	s, b = call(t, "POST", base+"/copy", map[string]any{"locator": map[string]string{"node_id": id}, "parent": parent, "name": "copy.txt"}, h)
	requireStatus(t, s, 400, b)
	h["Idempotency-Key"] = "019ad06b-7d00-7000-8400-" + suffix
	copyIn := map[string]any{"locator": map[string]string{"node_id": id}, "parent": parent, "name": "copy.txt"}
	copyIn["text"] = "unexpected body"
	s, b = call(t, "POST", base+"/copy", copyIn, h)
	requireStatus(t, s, 400, b)
	delete(copyIn, "text")
	s, b = call(t, "POST", base+"/copy", copyIn, h)
	requireStatus(t, s, 201, b)
	copied := jsonMap(t, b)["node_id"]
	s, b = call(t, "POST", base+"/copy", copyIn, h)
	requireStatus(t, s, 201, b)
	if jsonMap(t, b)["node_id"] != copied {
		t.Fatal("copy duplicated")
	}
	delete(h, "Idempotency-Key")
	s, b = call(t, "POST", base+"/trash", map[string]any{"locator": map[string]string{"node_id": id}}, h)
	requireStatus(t, s, 200, b)
	trash := jsonMap(t, b)
	entry := trash["id"].(string)
	s, b = call(t, "GET", base+"/stat?node_id="+id, nil, h)
	requireStatus(t, s, 404, b)
	delete(h, "If-Match")
	s, b = call(t, "GET", base+"/content?node_id="+id, nil, h)
	requireStatus(t, s, 404, b)
	h["If-Match"] = "\"3\""
	s, b = call(t, "POST", base+"/trash/"+entry+"/restore", map[string]any{}, h)
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["id"] != id || jsonMap(t, b)["revision"] != "4" {
		t.Fatal("restore changed identity or revision", string(b))
	}
	s, b = call(t, "POST", base+"/trash", map[string]any{"locator": map[string]string{"node_id": id}}, h)
	requireStatus(t, s, 412, b)
	// A replacement path can have the same revision as its predecessor; identity still fences it.
	h["If-Match"] = "\"4\""
	s, b = call(t, "POST", base+"/rename", map[string]any{"locator": map[string]string{"node_id": id}, "name": "renamed.txt"}, h)
	requireStatus(t, s, 200, b)
	s, b = call(t, "POST", base+"/text", map[string]any{"parent": parent, "name": "a.txt", "text": "replacement"}, h)
	requireStatus(t, s, 201, b)
	h["If-Match"] = "\"1\""
	s, b = call(t, "POST", base+"/trash", map[string]any{"locator": map[string]string{"path": "/drive/a.txt", "expected_node_id": id}}, h)
	requireStatus(t, s, 412, b)
	s, b = call(t, "POST", base+"/move", map[string]any{"locator": map[string]string{"node_id": folder}, "parent": map[string]string{"node_id": folder}}, h)
	requireStatus(t, s, 409, b)
	s, b = call(t, "GET", strings.TrimSuffix(base, "/files")+"/usage", nil, h)
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["used_bytes"] != "25" {
		t.Fatal("quota accounting", string(b))
	}

	// A detached directory hides every descendant by ID without rewriting descendant edges.
	s, b = call(t, "POST", base+"/text", map[string]any{"parent": map[string]string{"node_id": folder}, "name": "child", "text": "child"}, h)
	requireStatus(t, s, 201, b)
	child := jsonMap(t, b)["id"].(string)
	h["If-Match"] = "\"2\""
	s, b = call(t, "POST", base+"/trash", map[string]any{"locator": map[string]string{"node_id": folder}}, h)
	requireStatus(t, s, 200, b)
	directoryEntry := jsonMap(t, b)["id"].(string)
	s, b = call(t, "GET", base+"/stat?node_id="+child, nil, h)
	requireStatus(t, s, 404, b)
	h["If-Match"] = "\"3\""
	s, b = call(t, "POST", base+"/trash/"+directoryEntry+"/restore", map[string]any{}, h)
	requireStatus(t, s, 200, b)
	s, b = call(t, "GET", base+"/stat?node_id="+child, nil, h)
	requireStatus(t, s, 200, b)
	h["If-Match"] = "\"5\""
	s, b = call(t, "POST", base+"/trash", map[string]any{"locator": map[string]string{"node_id": id}}, h)
	requireStatus(t, s, 200, b)
	purgeEntry := jsonMap(t, b)["id"].(string)
	h["If-Match"] = "\"6\""
	s, b = call(t, "DELETE", base+"/trash/"+purgeEntry, nil, h)
	requireStatus(t, s, 204, b)
	s, b = call(t, "DELETE", base+"/trash/"+purgeEntry, nil, h)
	requireStatus(t, s, 404, b)
	s, b = call(t, "GET", strings.TrimSuffix(base, "/files")+"/usage", nil, h)
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["used_bytes"] != "23" {
		t.Fatal("purge debit repeated or lost", string(b))
	}
	viewer, viewerID, _ := onboard(t, "user_viewer_"+suffix, "viewer-"+suffix+"@example.test", "019ad06b-7d00-7000-9400-"+suffix, 0)
	workspaceBase := strings.TrimSuffix(base, "/files")
	s, b = call(t, "POST", workspaceBase+"/invitations", map[string]string{"email": "viewer-" + suffix + "@example.test", "role": "viewer"}, h)
	requireStatus(t, s, 201, b)
	token := jsonMap(t, b)["token"].(string)
	vh := map[string]string{"Authorization": "Bearer " + viewer, "If-Match": "\"1\""}
	s, b = call(t, "POST", "http://envoy:8080/v1/invitations/accept", map[string]string{"token": token}, vh)
	requireStatus(t, s, 200, b)
	s, b = call(t, "GET", base+"/content?node_id="+fmt.Sprint(copied), nil, map[string]string{"Authorization": vh["Authorization"]})
	requireStatus(t, s, 200, b)
	prepared := prepareUpload(t, base, map[string]any{"parent": parent, "name": "report.pdf"}, []byte("unparsed document"), "inline", h)
	transferUpload(t, base, prepared, []byte("unparsed document"), h)
	s, b = call(t, "POST", base+"/uploads/"+prepared["id"].(string)+"/finalize", nil, h)
	requireStatus(t, s, 200, b)
	source := jsonMap(t, b)["node_id"].(string)
	s, b = call(t, "GET", base+"/artifact-status?node_id="+source, nil, vh)
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["source_id"] != source {
		t.Fatal("processing status switched source")
	}
	s, b = call(t, "GET", base+"/artifact-status?node_id="+fmt.Sprint(copied), nil, vh)
	requireStatus(t, s, 404, b)
	s, b = call(t, "GET", base+"/trash", nil, vh)
	requireStatus(t, s, 403, b)
	s, b = call(t, "POST", base+"/text", map[string]any{"parent": parent, "name": "denied", "text": "denied"}, vh)
	requireStatus(t, s, 403, b)
	s, b = call(t, "PATCH", workspaceBase+"/members/"+viewerID, map[string]string{"role": "editor"}, h)
	requireStatus(t, s, 204, b)
	s, b = call(t, "DELETE", base+"/trash/"+entry, nil, vh)
	requireStatus(t, s, 403, b)

	s, b = call(t, "GET", base+"/stat?path="+url.QueryEscape("/drive/copy.txt/"), nil, h)
	requireStatus(t, s, 200, b)
	s, b = call(t, "GET", base+"/stat?path=.&cwd_id="+fmt.Sprint(copied), nil, h)
	requireStatus(t, s, 200, b)
	s, b = call(t, "GET", base+"/content?path="+url.QueryEscape("/drive/copy.txt/"), nil, map[string]string{"Authorization": h["Authorization"]})
	requireStatus(t, s, 400, b)

}
func TestFilesystemQuota(t *testing.T) {
	credential, e := os.ReadFile("/run/secrets/workspace_service_token")
	if e != nil {
		t.Fatal(e)
	}
	h := map[string]string{"Authorization": "Bearer " + strings.TrimSpace(string(credential))}
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	bucket := "019ad06b-7d00-7000-8500-" + suffix
	s, b := call(t, "POST", "http://letfs:8080/internal/v1/quota-buckets/ensure", map[string]string{"id": bucket, "provision_key": "quota-" + suffix, "limit_bytes": "6"}, h)
	requireStatus(t, s, 200, b)
	fsIDs := []string{"019ad06b-7d00-7000-8600-" + suffix, "019ad06b-7d00-7000-8700-" + suffix}
	roots := []string{"019ad06b-7d00-7000-8800-" + suffix, "019ad06b-7d00-7000-8900-" + suffix}
	for i, fs := range fsIDs {
		s, b = call(t, "POST", "http://letfs:8080/internal/v1/filesystems/ensure", map[string]string{"id": fs, "bucket_id": bucket, "root_id": roots[i], "provision_key": "quota-fs-" + fs, "root_name": "drive"}, h)
		requireStatus(t, s, 200, b)
	}

	db := serviceDB(t, "letfs")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	blocker, e := db.Begin(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer blocker.Rollback(context.Background())
	if _, e = blocker.Exec(ctx, "SELECT id FROM quota_buckets WHERE id=$1 FOR UPDATE", bucket); e != nil {
		t.Fatal(e)
	}
	start := make(chan struct{})
	results := make(chan int, 2)
	var wg sync.WaitGroup
	for i, fs := range fsIDs {
		wg.Add(1)
		go func(i int, fs string) {
			defer wg.Done()
			<-start
			s, _ := call(t, "POST", "http://letfs:8080/internal/v1/filesystems/"+fs+"/files/text", map[string]any{"scope": map[string]any{"actor_id": roots[i], "mounts": []any{map[string]string{"path": "/drive", "filesystem_id": fs}}}, "input": map[string]any{"parent": map[string]string{"node_id": roots[i]}, "name": "a", "text": "four"}}, h)
			results <- s
		}(i, fs)
	}
	close(start)
	observer := serviceDB(t, "letfs")
	for {
		var waiting int
		if e = observer.QueryRow(ctx, "SELECT count(*) FROM pg_stat_activity WHERE usename=current_user AND wait_event_type='Lock'").Scan(&waiting); e != nil {
			t.Fatal(e)
		}
		if waiting >= 2 {
			break
		}
		if ctx.Err() != nil {
			t.Fatal("both quota writers did not reach lock barrier")
		}
	}
	if e = blocker.Commit(ctx); e != nil {
		t.Fatal(e)
	}
	wg.Wait()
	close(results)
	counts := map[int]int{}
	for s := range results {
		counts[s]++
	}
	if counts[201] != 1 || counts[409] != 1 {
		t.Fatal("oversubscribed shared bucket", counts)
	}
	s, b = call(t, "GET", "http://letfs:8080/internal/v1/quota-buckets/"+bucket, nil, h)
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["used_bytes"] != "4" {
		t.Fatal("incorrect usage", string(b))
	}
	scope := map[string]any{"actor_id": roots[0], "mounts": []any{map[string]string{"path": "/drive", "filesystem_id": fsIDs[0]}, map[string]string{"path": "/other", "filesystem_id": fsIDs[1]}}}
	internal := "http://letfs:8080/internal/v1/filesystems/" + fsIDs[0] + "/files/"
	s, b = call(t, "POST", internal+"stat", map[string]any{"scope": scope, "input": map[string]any{"locator": map[string]string{"node_id": roots[1]}}}, h)
	requireStatus(t, s, 404, b)
	s, b = call(t, "POST", internal+"stat", map[string]any{"scope": scope, "input": map[string]any{"locator": map[string]string{"path": "/other"}}}, h)
	requireStatus(t, s, 409, b)
	// Empty directory admission consumes the same transactional node cap as files/trash.
	if _, e = db.Exec(context.Background(), "UPDATE filesystems SET max_nodes=node_count WHERE id=$1", fsIDs[0]); e != nil {
		t.Fatal(e)
	}
	s, b = call(t, "POST", internal+"directories", map[string]any{"scope": scope, "input": map[string]any{"parent": map[string]string{"node_id": roots[0]}, "name": "no-slot"}}, h)
	requireStatus(t, s, 409, b)

}
