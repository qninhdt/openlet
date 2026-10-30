package e2e

import (
	"bytes"
	"fmt"
	"github.com/google/uuid"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestWorkerRecovery(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, actor, ws := onboard(t, "user_worker_"+suffix, "worker-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	parent := map[string]string{"node_id": root}
	content := []byte{0, 4, 5, 6}
	prepared := prepareUpload(t, base, map[string]any{"parent": parent, "name": "recovery-source"}, content, "object", h)
	upload := prepared["id"].(string)
	transferUpload(t, base, prepared, content, h)
	s, b = call(t, "POST", base+"/uploads/"+upload+"/finalize", nil, h)
	requireStatus(t, s, 200, b)
	source := jsonMap(t, b)["node_id"].(string)
	s, b = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{"block_copy": true}, nil)
	requireStatus(t, s, 204, b)
	key := uuid.NewString()
	h["If-Match"] = "\"1\""
	h["Idempotency-Key"] = key
	in := map[string]any{"locator": map[string]string{"node_id": source}, "parent": parent, "name": "recovered-copy"}
	s, b = call(t, "POST", base+"/copy", in, h)
	requireStatus(t, s, 202, b)
	operation := jsonMap(t, b)
	deadline := time.Now().Add(20 * time.Second)
	for {
		s, b = call(t, "GET", "http://issuer:8080/control/storage", nil, nil)
		requireStatus(t, s, 200, b)
		if jsonMap(t, b)["copy_seen"] == true {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("copy provider barrier not reached")
		}
		time.Sleep(10 * time.Millisecond)
	}
	directory := os.Getenv("OPENLET_HISTORY_DIR")
	if directory == "" {
		t.Fatal("recovery marker directory required")
	}
	if e := os.WriteFile(filepath.Join(directory, "recovery-ready"), []byte("copy checkpoint persisted"), 0600); e != nil {
		t.Fatal(e)
	}
	deadline = time.Now().Add(180 * time.Second)
	for {
		if _, e := os.Stat(filepath.Join(directory, "recovery-resume")); e == nil {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("host did not restart workers")
		}
		time.Sleep(20 * time.Millisecond)
	}
	s, b = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{}, nil)
	requireStatus(t, s, 204, b)
	result := waitFileOperation(t, operation["status_url"].(string), h)
	s, b = call(t, "POST", base+"/copy", in, h)
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["node_id"] != result {
		t.Fatal("restart duplicated publication")
	}
	s, b = call(t, "GET", base+"/content?node_id="+result, nil, map[string]string{"Authorization": h["Authorization"]})
	requireStatus(t, s, 200, b)
	if !bytes.Equal(b, content) {
		t.Fatal("restart changed bytes")
	}
	fs := filesystemForNode(t, root)
	db := serviceDB(t, "letfs")
	var used int64
	if e := db.QueryRow(t.Context(), "SELECT used_bytes FROM quota_buckets WHERE id=(SELECT bucket_id FROM filesystems WHERE id=$1)", fs).Scan(&used); e != nil || used != 8 {
		t.Fatal("restart charged twice", used, e)
	}
	saveHistory(t, "copy/"+fs+"/"+actor+"/"+key, "CopyNodeRecovery")
}
