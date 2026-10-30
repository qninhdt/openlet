package e2e

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"context"
	"github.com/google/uuid"
	temporalclient "go.temporal.io/sdk/client"
)

func TestProcessingRecovery(t *testing.T) {
	directory := os.Getenv("OPENLET_HISTORY_DIR")
	if directory == "" {
		t.Fatal("OPENLET_HISTORY_DIR required for the kill/restart barrier")
	}
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, _, ws := onboard(t, "user_processing_recovery_"+suffix, "processing-recovery-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	original, err := os.ReadFile("/processing-fixtures/tiny.docx")
	if err != nil {
		t.Fatal(err)
	}
	s, b = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{"block_get": true}, nil)
	requireStatus(t, s, 204, b)
	defer func() { call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{}, nil) }()
	prepared := prepareUpload(t, base, map[string]any{"parent": map[string]string{"node_id": root}, "name": "retry.docx"}, original, "object", h)
	transferUpload(t, base, prepared, original, h)
	s, b = call(t, "POST", base+"/uploads/"+prepared["id"].(string)+"/finalize", nil, h)
	requireStatus(t, s, 200, b)
	source := jsonMap(t, b)["node_id"].(string)
	deadline := time.Now().Add(60 * time.Second)
	for {
		s, b = call(t, "GET", "http://issuer:8080/control/storage", nil, nil)
		requireStatus(t, s, 200, b)
		if jsonMap(t, b)["get_seen"] == true {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("processing did not reach the real source GET barrier")
		}
		time.Sleep(50 * time.Millisecond)
	}
	if err = os.WriteFile(filepath.Join(directory, "processing-recovery-ready"), []byte("source GET pending\n"), 0600); err != nil {
		t.Fatal(err)
	}
	deadline = time.Now().Add(90 * time.Second)
	for {
		_, err = os.Stat(filepath.Join(directory, "processing-recovery-resume"))
		if err == nil {
			break
		}
		if !os.IsNotExist(err) || time.Now().After(deadline) {
			t.Fatal("processor kill/restart barrier", err)
		}
		time.Sleep(50 * time.Millisecond)
	}
	s, b = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{}, nil)
	requireStatus(t, s, 204, b)
	deadline = time.Now().Add(120 * time.Second)
	var operation string
	for {
		s, b = call(t, "GET", base+"/artifact-status?node_id="+source, nil, h)
		requireStatus(t, s, 200, b)
		state := jsonMap(t, b)
		operation = state["operation_id"].(string)
		if state["state"] == "succeeded" {
			break
		}
		if state["state"] == "failed" || time.Now().After(deadline) {
			t.Fatalf("retry did not publish: %s", b)
		}
		time.Sleep(100 * time.Millisecond)
	}
	db := serviceDB(t, "letfs")
	var generation, children int
	if err = db.QueryRow(t.Context(), "SELECT attempt_generation FROM operations WHERE id=$1", operation).Scan(&generation); err != nil || generation < 2 {
		t.Fatal("worker retry did not fence the first generation", generation, err)
	}
	if err = db.QueryRow(t.Context(), "SELECT count(*) FROM nodes WHERE parent_id=$1", source).Scan(&children); err != nil || children != 3 {
		t.Fatal("retry duplicated or lost children", children, err)
	}
	s, b = call(t, "GET", base+"/content?node_id="+source, nil, h)
	requireStatus(t, s, 200, b)
	if !bytes.Equal(b, original) {
		t.Fatal("retry changed the source")
	}
	s, b = call(t, "GET", base+"/content?path=/drive/retry.docx/001-introduction.md", nil, h)
	requireStatus(t, s, 200, b)
	if !strings.Contains(string(b), "Hello document.") {
		t.Fatal("retry lost converted bytes")
	}
	saveHistory(t, "process-file/"+operation, "ProcessFileRecovery")
}

func TestProcessingExhausted(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, _, ws := onboard(t, "user_processing_failed_"+suffix, "processing-failed-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	original, err := os.ReadFile("/processing-fixtures/tiny.docx")
	if err != nil {
		t.Fatal(err)
	}
	s, b = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{"fail_get": true}, nil)
	requireStatus(t, s, 204, b)
	defer func() { call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{}, nil) }()
	prepared := prepareUpload(t, base, map[string]any{"parent": map[string]string{"node_id": root}, "name": "failed.docx"}, original, "object", h)
	transferUpload(t, base, prepared, original, h)
	s, b = call(t, "POST", base+"/uploads/"+prepared["id"].(string)+"/finalize", nil, h)
	requireStatus(t, s, 200, b)
	source := jsonMap(t, b)["node_id"].(string)
	s, b = call(t, "GET", base+"/artifact-status?node_id="+source, nil, h)
	requireStatus(t, s, 200, b)
	op := jsonMap(t, b)["operation_id"].(string)
	tc, err := temporalclient.Dial(temporalclient.Options{HostPort: "temporal:7233", Namespace: "openlet"})
	if err != nil {
		t.Fatal(err)
	}
	defer tc.Close()
	ctx, cancel := context.WithTimeout(t.Context(), 60*time.Second)
	defer cancel()
	if err = tc.GetWorkflow(ctx, "process-file/"+op, "").Get(ctx, nil); err == nil || ctx.Err() != nil {
		t.Fatal("expected exhausted activity retries", err)
	}
	s, b = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{}, nil)
	requireStatus(t, s, 204, b)
	db := serviceDB(t, "letfs")
	var generation int
	if err = db.QueryRow(ctx, "SELECT attempt_generation FROM operations WHERE id=$1", op).Scan(&generation); err != nil || generation != 3 {
		t.Fatal("retry limit", generation, err)
	}
	for {
		run, err := tc.ExecuteWorkflow(ctx, temporalclient.StartWorkflowOptions{ID: "processing-failure-maintenance/" + uuid.NewString(), TaskQueue: "openlet-letfs"}, "StorageMaintenance", nil)
		if err != nil {
			t.Fatal(err)
		}
		if err = run.Get(ctx, nil); err != nil {
			t.Fatal(err)
		}
		s, b = call(t, "GET", base+"/artifact-status?node_id="+source, nil, h)
		requireStatus(t, s, 200, b)
		if jsonMap(t, b)["state"] == "failed" {
			break
		}
		if ctx.Err() != nil {
			t.Fatal("closed workflow was not reconciled", ctx.Err())
		}
	}
	if jsonMap(t, b)["error_code"] != "PROCESSING_FAILED" {
		t.Fatal("wrong terminal status", string(b))
	}
	s, b = call(t, "GET", base+"/list?node_id="+source, nil, h)
	requireStatus(t, s, 200, b)
	if len(jsonMap(t, b)["items"].([]any)) != 0 {
		t.Fatal("failed processing exposed children")
	}
	s, b = call(t, "GET", base+"/content?node_id="+source, nil, h)
	requireStatus(t, s, 200, b)
	if !bytes.Equal(b, original) {
		t.Fatal("failed processing changed original")
	}
	saveHistory(t, "process-file/"+op, "ProcessFileExhausted")
}
