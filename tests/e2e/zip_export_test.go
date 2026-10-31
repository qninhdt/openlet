package e2e

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestZipExport(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, actor, ws := onboard(t, "user_zip_"+suffix, "zip-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	headers := map[string]string{"Authorization": "Bearer " + jwt}
	status, body := call(t, "GET", base+"/stat?path=/drive", nil, headers)
	requireStatus(t, status, 200, body)
	root := jsonMap(t, body)["id"].(string)
	status, body = call(t, "POST", base+"/directories", map[string]any{"parent": map[string]string{"node_id": root}, "name": "folder"}, headers)
	requireStatus(t, status, 201, body)
	folder := jsonMap(t, body)["id"].(string)
	status, body = call(t, "POST", base+"/directories", map[string]any{"parent": map[string]string{"node_id": folder}, "name": "empty"}, headers)
	requireStatus(t, status, 201, body)
	original, err := os.ReadFile("/processing-fixtures/tiny.docx")
	if err != nil {
		t.Fatal(err)
	}
	originals := map[string][]byte{"report.docx": original, "image.png": {0, 1, 2, 255}}
	var source string
	for _, name := range []string{"report.docx", "image.png"} {
		mode := "object"
		if name == "report.docx" {
			mode = "inline"
		}
		prepared := prepareUpload(t, base, map[string]any{"parent": map[string]string{"node_id": folder}, "name": name}, originals[name], mode, headers)
		transferUpload(t, base, prepared, originals[name], headers)
		status, body = call(t, "POST", base+"/uploads/"+prepared["id"].(string)+"/finalize", map[string]any{}, headers)
		requireStatus(t, status, 200, body)
		if name == "report.docx" {
			source = jsonMap(t, body)["node_id"].(string)
		}
	}
	deadline := time.Now().Add(90 * time.Second)
	for {
		status, body = call(t, "GET", base+"/processing-status?node_id="+source, nil, headers)
		requireStatus(t, status, 200, body)
		state := processingStage(t, jsonMap(t, body), "enrichment")["state"]
		if state == "succeeded" {
			break
		}
		if state == "failed" || time.Now().After(deadline) {
			t.Fatalf("processing: %s", body)
		}
		time.Sleep(100 * time.Millisecond)
	}
	for _, artifacts := range []bool{false, true} {
		selected := folder
		if artifacts {
			selected = source
		}
		key := uuid.NewString()
		admission := map[string]string{"Authorization": "Bearer " + jwt, "Idempotency-Key": key}
		input := map[string]any{"locators": []any{map[string]string{"node_id": selected}}, "artifacts": artifacts}
		status, body = call(t, "POST", base+"/exports", input, admission)
		if status != 200 && status != 202 {
			t.Fatal(status, string(body))
		}
		operation := jsonMap(t, body)["operation_id"].(string)
		location := base + "/exports/" + operation
		deadline = time.Now().Add(60 * time.Second)
		for {
			status, body = call(t, "GET", location, nil, headers)
			requireStatus(t, status, 200, body)
			state := jsonMap(t, body)["state"]
			if state == "succeeded" {
				break
			}
			if state == "failed" || time.Now().After(deadline) {
				t.Fatalf("export: %s", body)
			}
			time.Sleep(100 * time.Millisecond)
		}
		status, body = call(t, "POST", base+"/exports", input, admission)
		requireStatus(t, status, 200, body)
		if jsonMap(t, body)["operation_id"] != operation {
			t.Fatal("duplicate export")
		}
		status, body = call(t, "GET", location+"/download", nil, headers)
		requireStatus(t, status, 200, body)
		download := jsonMap(t, body)["download"].(map[string]any)["url"].(string)
		status, body = rawCall(t, "GET", download, nil, map[string]string{"Range": "bytes=0-3"})
		requireStatus(t, status, 206, body)
		if !bytes.Equal(body, []byte{'P', 'K', 3, 4}) {
			t.Fatal("invalid ZIP signature")
		}
		status, body = rawCall(t, "GET", download, nil, nil)
		requireStatus(t, status, 200, body)
		archive, err := zip.NewReader(bytes.NewReader(body), int64(len(body)))
		if err != nil {
			t.Fatal(err)
		}
		items := map[string][]byte{}
		for _, entry := range archive.File {
			reader, err := entry.Open()
			if err != nil {
				t.Fatal(err)
			}
			data, err := io.ReadAll(reader)
			reader.Close()
			if err != nil {
				t.Fatal(err)
			}
			items[entry.Name] = data
		}
		if artifacts {
			if len(items) != 2 || !strings.Contains(string(items["README.md"]), "Hello document.") || !strings.Contains(string(items["README.md"]), "Done.") {
				t.Fatal("incorrect artifact ZIP", items)
			}
			if !strings.Contains(string(items["untitled.csv"]), "Apple,3") {
				t.Fatal("lost table CSV", items)
			}
			if jsonMap(t, mustExportStatus(t, location, headers))["name"] != "report.docx-artifacts.zip" {
				t.Fatal("incorrect artifact filename")
			}
		} else {
			if len(items) != 4 {
				t.Fatal("folder must contain root, empty directory and two originals", items)
			}
			for name, data := range originals {
				if !bytes.Equal(items["folder/"+name], data) {
					t.Fatal("wrong original", name)
				}
			}
			if _, ok := items["folder/empty/"]; !ok {
				t.Fatal("lost empty folder")
			}
			saveHistory(t, "export-archive/"+filesystemForNode(t, folder)+"/"+actor+"/"+key, "ExportArchive")
		}
	}
}
func mustExportStatus(t *testing.T, url string, headers map[string]string) []byte {
	t.Helper()
	status, body := call(t, "GET", url, nil, headers)
	requireStatus(t, status, 200, body)
	return body
}

func TestZipExportRetry(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, actor, ws := onboard(t, "user_zip_retry_"+suffix, "zip-retry-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	headers := map[string]string{"Authorization": "Bearer " + jwt}
	status, body := call(t, "GET", base+"/stat?path=/drive", nil, headers)
	requireStatus(t, status, 200, body)
	root := jsonMap(t, body)["id"].(string)
	original := []byte{0, 1, 2, 255}
	prepared := prepareUpload(t, base, map[string]any{"parent": map[string]string{"node_id": root}, "name": "before.png"}, original, "object", headers)
	transferUpload(t, base, prepared, original, headers)
	status, body = call(t, "POST", base+"/uploads/"+prepared["id"].(string)+"/finalize", nil, headers)
	requireStatus(t, status, 200, body)
	source := jsonMap(t, body)["node_id"].(string)
	status, body = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{"block_get": true}, nil)
	requireStatus(t, status, 204, body)
	defer func() { call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{}, nil) }()
	key := uuid.NewString()
	status, body = call(t, "POST", base+"/exports", map[string]any{"locators": []any{map[string]string{"node_id": source}}}, map[string]string{"Authorization": "Bearer " + jwt, "Idempotency-Key": key})
	if status != 200 && status != 202 {
		t.Fatal(status, string(body))
	}
	operation := jsonMap(t, body)["operation_id"].(string)
	deadline := time.Now().Add(30 * time.Second)
	for {
		status, body = call(t, "GET", "http://issuer:8080/control/storage", nil, nil)
		requireStatus(t, status, 200, body)
		if jsonMap(t, body)["get_seen"] == true {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("archive did not reach source GET barrier")
		}
		time.Sleep(50 * time.Millisecond)
	}
	status, body = call(t, "POST", base+"/rename", map[string]any{"locator": map[string]string{"node_id": source}, "name": "after.png"}, map[string]string{"Authorization": "Bearer " + jwt, "If-Match": "\"1\""})
	requireStatus(t, status, 200, body)
	status, body = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{}, nil)
	requireStatus(t, status, 204, body)
	location := base + "/exports/" + operation
	deadline = time.Now().Add(60 * time.Second)
	for {
		body = mustExportStatus(t, location, headers)
		state := jsonMap(t, body)["state"]
		if state == "succeeded" {
			break
		}
		if state == "failed" || time.Now().After(deadline) {
			t.Fatalf("changed input did not retry: %s", body)
		}
		time.Sleep(50 * time.Millisecond)
	}
	var generation int
	if err := serviceDB(t, "letfs").QueryRow(t.Context(), "SELECT attempt_generation FROM operations WHERE id=$1", operation).Scan(&generation); err != nil || generation != 2 {
		t.Fatal("expected second archive attempt", generation, err)
	}
	status, body = call(t, "GET", location+"/download", nil, headers)
	requireStatus(t, status, 200, body)
	status, body = rawCall(t, "GET", jsonMap(t, body)["download"].(map[string]any)["url"].(string), nil, nil)
	requireStatus(t, status, 200, body)
	archive, err := zip.NewReader(bytes.NewReader(body), int64(len(body)))
	if err != nil || len(archive.File) != 1 || archive.File[0].Name != "after.png" {
		t.Fatal("retry did not re-enumerate current names", err)
	}
	reader, err := archive.File[0].Open()
	if err != nil {
		t.Fatal(err)
	}
	defer reader.Close()
	data, err := io.ReadAll(reader)
	if err != nil || !bytes.Equal(data, original) {
		t.Fatal("retry changed original bytes", err)
	}
	saveHistory(t, "export-archive/"+filesystemForNode(t, source)+"/"+actor+"/"+key, "ExportArchiveRetry")
}

func TestZipExportQueryBounds(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, _, ws := onboard(t, "user_zip_queries_"+suffix, "zip-queries-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	headers := map[string]string{"Authorization": "Bearer " + jwt}
	db := serviceDB(t, "letfs")
	status, body := call(t, "GET", base+"/stat?path=/drive", nil, headers)
	requireStatus(t, status, 200, body)
	root := jsonMap(t, body)["id"].(string)
	count := func(pattern string) int64 {
		var n int64
		if err := db.QueryRow(t.Context(), "SELECT coalesce(sum(calls),0)::bigint FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database()) AND query LIKE $1", pattern).Scan(&n); err != nil {
			t.Fatal(err)
		}
		return n
	}
	const inline = "SELECT n.id,n.revision,d.inline_bytes FROM nodes n JOIN file_data d ON d.node_id=n.id WHERE n.id=ANY%"
	const tree = "WITH RECURSIVE tree(root,id,parent_id,name,kind,size_bytes,revision,parts,depth)%"
	for _, n := range []int{1, 65} {
		status, body := call(t, "POST", base+"/directories", map[string]any{"parent": map[string]string{"node_id": root}, "name": fmt.Sprintf("batch-%d", n)}, headers)
		requireStatus(t, status, 201, body)
		folder := jsonMap(t, body)["id"].(string)
		for i := 0; i < n; i++ {
			status, body = call(t, "POST", base+"/text", map[string]any{"parent": map[string]string{"node_id": folder}, "name": fmt.Sprintf("file-%03d.txt", i), "text": fmt.Sprintf("payload %d", i)}, headers)
			requireStatus(t, status, 201, body)
		}
		beforeInline, beforeTree := count(inline), count(tree)
		status, body = call(t, "POST", base+"/exports", map[string]any{"locators": []any{map[string]string{"node_id": folder}}}, map[string]string{"Authorization": "Bearer " + jwt, "Idempotency-Key": uuid.NewString()})
		if status != 200 && status != 202 {
			t.Fatal(status, string(body))
		}
		location := base + "/exports/" + jsonMap(t, body)["operation_id"].(string)
		deadline := time.Now().Add(60 * time.Second)
		for {
			status, body = call(t, "GET", location, nil, headers)
			requireStatus(t, status, 200, body)
			state := jsonMap(t, body)["state"]
			if state == "succeeded" {
				break
			}
			if state == "failed" || time.Now().After(deadline) {
				t.Fatalf("export: %s", body)
			}
			time.Sleep(50 * time.Millisecond)
		}
		if got, want := count(inline)-beforeInline, int64((n+63)/64); got != want {
			t.Fatalf("%d inline files used %d content statements, want %d", n, got, want)
		}
		if got := count(tree) - beforeTree; got != 3 {
			t.Fatalf("%d files used %d tree statements, want preflight, prepare and publish", n, got)
		}
	}
}
