package e2e

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"os"
	"testing"
	"time"
)

type backupFixture struct {
	Subject, Actor, Workspace, InlineNode, ObjectNode, InlineText, ObjectHex string
	SourceNode, SourceHex, ArtifactNode, ArtifactHex, ExportID, ExportDigest string
}

func TestBackupSeed(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	subject := "user_backup_" + suffix
	jwt, actor, ws := onboard(t, subject, "backup-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	parent := map[string]string{"node_id": root}
	text := "\ufeffrestored exactly\r\n"
	s, b = call(t, "POST", base+"/text", map[string]any{"parent": parent, "name": "inline-backup", "text": text}, h)
	requireStatus(t, s, 201, b)
	inline := jsonMap(t, b)["id"].(string)
	data := []byte{0, 255, 1, 2, 3, 4}
	prepared := prepareUpload(t, base, map[string]any{"parent": parent, "name": "object-backup"}, data, "object", h)
	upload := prepared["id"].(string)
	transferUpload(t, base, prepared, data, h)
	s, b = call(t, "POST", base+"/uploads/"+upload+"/finalize", nil, h)
	requireStatus(t, s, 200, b)
	f := backupFixture{Subject: subject, Actor: actor, Workspace: ws, InlineNode: inline, ObjectNode: jsonMap(t, b)["node_id"].(string), InlineText: text, ObjectHex: hex.EncodeToString(data)}
	document, e := os.ReadFile("/processing-fixtures/tiny.docx")
	if e != nil {
		t.Fatal(e)
	}
	prepared = prepareUpload(t, base, map[string]any{"parent": parent, "name": "report.docx"}, document, "object", h)
	transferUpload(t, base, prepared, document, h)
	s, b = call(t, "POST", base+"/uploads/"+prepared["id"].(string)+"/finalize", nil, h)
	requireStatus(t, s, 200, b)
	f.SourceNode, f.SourceHex = jsonMap(t, b)["node_id"].(string), hex.EncodeToString(document)
	deadline := time.Now().Add(90 * time.Second)
	for {
		s, b = call(t, "GET", base+"/artifact-status?node_id="+f.SourceNode, nil, h)
		requireStatus(t, s, 200, b)
		state := jsonMap(t, b)["state"]
		if state == "succeeded" {
			break
		}
		if state == "failed" || time.Now().After(deadline) {
			t.Fatalf("backup processing: %s", b)
		}
		time.Sleep(100 * time.Millisecond)
	}
	s, b = call(t, "GET", base+"/stat?path=/drive/report.docx/001-introduction.md", nil, h)
	requireStatus(t, s, 200, b)
	f.ArtifactNode = jsonMap(t, b)["id"].(string)
	s, b = call(t, "GET", base+"/content?node_id="+f.ArtifactNode, nil, h)
	requireStatus(t, s, 200, b)
	f.ArtifactHex = hex.EncodeToString(b)
	s, b = call(t, "POST", base+"/exports", map[string]any{"locators": []any{map[string]string{"node_id": root}}}, map[string]string{"Authorization": "Bearer " + jwt, "Idempotency-Key": uuid.NewString()})
	if s != 200 && s != 202 {
		t.Fatal(s, string(b))
	}
	f.ExportID = jsonMap(t, b)["operation_id"].(string)
	deadline = time.Now().Add(60 * time.Second)
	for {
		s, b = call(t, "GET", base+"/exports/"+f.ExportID, nil, h)
		requireStatus(t, s, 200, b)
		state := jsonMap(t, b)["state"]
		if state == "succeeded" {
			break
		}
		if state == "failed" || time.Now().After(deadline) {
			t.Fatalf("backup export: %s", b)
		}
		time.Sleep(100 * time.Millisecond)
	}
	s, b = call(t, "GET", base+"/exports/"+f.ExportID+"/download", nil, h)
	requireStatus(t, s, 200, b)
	s, b = rawCall(t, "GET", jsonMap(t, b)["download"].(map[string]any)["url"].(string), nil, nil)
	requireStatus(t, s, 200, b)
	digest := sha256.Sum256(b)
	f.ExportDigest = hex.EncodeToString(digest[:])
	path := os.Getenv("OPENLET_BACKUP_FIXTURE")
	if path == "" {
		t.Fatal("OPENLET_BACKUP_FIXTURE required")
	}
	raw, e := json.Marshal(f)
	if e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(path, raw, 0600); e != nil {
		t.Fatal(e)
	}
}
func TestBackupRestore(t *testing.T) {
	raw, e := os.ReadFile(os.Getenv("OPENLET_BACKUP_FIXTURE"))
	if e != nil {
		t.Fatal(e)
	}
	var f backupFixture
	if e = json.Unmarshal(raw, &f); e != nil {
		t.Fatal(e)
	}
	jwt := token(t, map[string]any{"sub": f.Subject, "openlet_user_id": f.Actor}, false)
	h := map[string]string{"Authorization": "Bearer " + jwt}
	base := "http://envoy:8080/v1/workspaces/" + f.Workspace + "/files"
	for id, want := range map[string][]byte{f.InlineNode: []byte(f.InlineText), f.ObjectNode: mustDecode(t, f.ObjectHex), f.SourceNode: mustDecode(t, f.SourceHex), f.ArtifactNode: mustDecode(t, f.ArtifactHex)} {
		s, b := call(t, "GET", base+"/content?node_id="+id, nil, h)
		requireStatus(t, s, 200, b)
		if !bytes.Equal(b, want) {
			t.Fatal("restored bytes changed")
		}
	}
	s, b := call(t, "GET", base+"/exports/"+f.ExportID+"/download", nil, h)
	requireStatus(t, s, 200, b)
	url := jsonMap(t, b)["download"].(map[string]any)["url"].(string)
	s, b = rawCall(t, "GET", url, nil, map[string]string{"Range": "bytes=0-3"})
	requireStatus(t, s, 206, b)
	if !bytes.Equal(b, []byte{'P', 'K', 3, 4}) {
		t.Fatal("restored export is not readable")
	}
	s, b = rawCall(t, "GET", url, nil, nil)
	requireStatus(t, s, 200, b)
	digest := sha256.Sum256(b)
	if hex.EncodeToString(digest[:]) != f.ExportDigest {
		t.Fatal("restored export bytes changed")
	}
	db := serviceDB(t, "letfs")
	var drift int
	if e = db.QueryRow(t.Context(), `SELECT count(*) FROM quota_buckets b WHERE used_bytes<>(SELECT coalesce(sum(n.size_bytes),0) FROM nodes n JOIN filesystems f ON f.id=n.filesystem_id LEFT JOIN operations o ON o.id=n.staging_operation_id WHERE f.bucket_id=b.id AND (n.staging_operation_id IS NULL OR o.state='succeeded'))`).Scan(&drift); e != nil || drift != 0 {
		t.Fatal("restored usage drift", drift, e)
	}
	saveHistory(t, "onboard/"+f.Subject, "RestoredOnboardUser")
}
func mustDecode(t *testing.T, s string) []byte {
	t.Helper()
	b, e := hex.DecodeString(s)
	if e != nil {
		t.Fatal(e)
	}
	return b
}
