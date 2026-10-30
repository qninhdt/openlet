package e2e

import (
	"bytes"
	"crypto/md5"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"io"
	"net/http"
	"testing"
	"time"
)

func rawCall(t *testing.T, method, url string, data []byte, headers map[string]string) (int, []byte) {
	t.Helper()
	r, e := http.NewRequest(method, url, bytes.NewReader(data))
	if e != nil {
		t.Fatal(e)
	}
	for k, v := range headers {
		r.Header.Set(k, v)
	}
	res, e := client.Do(r)
	if e != nil {
		t.Fatal(e)
	}
	defer res.Body.Close()
	body, e := io.ReadAll(res.Body)
	if e != nil {
		t.Fatal(e)
	}
	recordContract(t, method, url, res.StatusCode, body)
	return res.StatusCode, body
}
func TestStorageUploads(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, actor, ws := onboard(t, "user_storage_"+suffix, "storage-"+suffix+"@example.test", "019ad06b-7d00-7000-9500-"+suffix, 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	parent := map[string]string{"node_id": root}
	var uploaded []string
	for i, data := range [][]byte{[]byte("\xef\xbb\xbfexact\r\n"), {0, 1, 2, 255}, bytes.Repeat([]byte("large text\n"), 600000)} {
		name := fmt.Sprintf("upload-%d", i)
		mode := "object"
		if i == 0 {
			mode = "inline"
		}
		prepared := prepareUpload(t, base, map[string]any{"parent": parent, "name": name}, data, mode, h)
		upload := prepared["id"].(string)
		transferUpload(t, base, prepared, data, h)
		if mode == "inline" {
			s, b = rawCall(t, "PUT", base+"/uploads/"+upload+"/bytes", data, h)
			requireStatus(t, s, 200, b)
		} else {
			s, b = rawCall(t, "PUT", base+"/uploads/"+upload+"/bytes", data, h)
			expected := 409
			if len(data) > 262144 {
				expected = 413
			}
			requireStatus(t, s, expected, b)
		}
		s, b = call(t, "POST", base+"/uploads/"+upload+"/finalize", nil, h)
		requireStatus(t, s, 200, b)
		node := jsonMap(t, b)["node_id"].(string)
		uploaded = append(uploaded, node)
		s, b = call(t, "POST", base+"/uploads/"+upload+"/finalize", nil, h)
		requireStatus(t, s, 200, b)
		if jsonMap(t, b)["node_id"] != node {
			t.Fatal("finalize duplicated node")
		}
		s, b = call(t, "GET", base+"/content?node_id="+node, nil, h)
		requireStatus(t, s, 200, b)
		if !bytes.Equal(data, b) {
			t.Fatal("upload bytes changed")
		}
		h["Range"] = "bytes=1-2"
		s, b = call(t, "GET", base+"/content?node_id="+node, nil, h)
		requireStatus(t, s, 206, b)
		if !bytes.Equal(data[1:3], b) {
			t.Fatal("object range mismatch")
		}
		delete(h, "Range")
		db := serviceDB(t, "letfs")
		var storage string
		if e := db.QueryRow(t.Context(), "SELECT storage_kind FROM file_data WHERE node_id=$1", node).Scan(&storage); e != nil {
			t.Fatal(e)
		}
		want := "object"
		if i == 0 {
			want = "inline"
		}
		if storage != want {
			t.Fatal("wrong classification", storage, want)
		}
	}
	// Lose one provider acknowledgment after the independent object has actually been copied.
	s, b = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{"lose_copy": 1}, nil)
	requireStatus(t, s, 204, b)
	// Object copy creates independent storage, and directory copy publishes a complete detached tree.
	h["If-Match"] = "\"1\""
	h["Idempotency-Key"] = "019ad06b-7d00-7000-9600-" + suffix
	s, b = call(t, "POST", base+"/copy", map[string]any{"locator": map[string]string{"node_id": uploaded[1]}, "parent": parent, "name": "object-copy"}, h)
	requireStatus(t, s, 202, b)
	operation := jsonMap(t, b)
	copyID := waitFileOperation(t, operation["status_url"].(string), h)
	saveHistory(t, "copy/"+filesystemForNode(t, root)+"/"+actor+"/"+h["Idempotency-Key"], "CopyNode")
	s, b = call(t, "GET", base+"/content?node_id="+copyID, nil, map[string]string{"Authorization": h["Authorization"]})
	requireStatus(t, s, 200, b)
	if !bytes.Equal(b, []byte{0, 1, 2, 255}) {
		t.Fatal("object copy bytes")
	}
	db := serviceDB(t, "letfs")
	var keys int
	if e := db.QueryRow(t.Context(), "SELECT count(DISTINCT object_key) FROM file_data WHERE node_id=ANY($1::uuid[])", []string{uploaded[1], copyID}).Scan(&keys); e != nil || keys != 2 {
		t.Fatal("copy reused object key", keys, e)
	}
	delete(h, "If-Match")
	delete(h, "Idempotency-Key")
	s, b = call(t, "POST", base+"/directories", map[string]any{"parent": parent, "name": "source-dir"}, h)
	requireStatus(t, s, 201, b)
	dir := jsonMap(t, b)["id"].(string)
	s, b = call(t, "POST", base+"/text", map[string]any{"parent": map[string]string{"node_id": dir}, "name": "note", "text": "copied"}, h)
	requireStatus(t, s, 201, b)
	h["If-Match"] = "\"2\""
	h["Idempotency-Key"] = "019ad06b-7d00-7000-9700-" + suffix
	s, b = call(t, "POST", base+"/copy", map[string]any{"locator": map[string]string{"node_id": dir}, "parent": parent, "name": "copied-dir"}, h)
	requireStatus(t, s, 202, b)
	operation = jsonMap(t, b)
	copiedDir := waitFileOperation(t, operation["status_url"].(string), h)
	s, b = call(t, "GET", base+"/list?node_id="+copiedDir, nil, h)
	requireStatus(t, s, 200, b)
	children := jsonMap(t, b)["items"].([]any)
	if len(children) != 1 || children[0].(map[string]any)["name"] != "note" {
		t.Fatal("directory copy incomplete", string(b))
	}
	delete(h, "If-Match")
	delete(h, "Idempotency-Key")

	// Captured overwrite preconditions survive the transfer and preserve a concurrent edit.
	s, b = call(t, "POST", base+"/text", map[string]any{"parent": parent, "name": "old", "text": "old"}, h)
	requireStatus(t, s, 201, b)
	old := jsonMap(t, b)["id"].(string)
	h["If-Match"] = "\"1\""
	data := []byte{0, 1, 2}
	prepared := prepareUpload(t, base, map[string]any{"locator": map[string]string{"node_id": old}}, data, "object", h)
	upload := prepared["id"].(string)
	s, b = call(t, "PUT", base+"/text", map[string]any{"locator": map[string]string{"node_id": old}, "text": "new"}, h)
	requireStatus(t, s, 200, b)
	transferUpload(t, base, prepared, data, h)
	s, b = call(t, "POST", base+"/uploads/"+upload+"/finalize", nil, h)
	requireStatus(t, s, 412, b)
	s, b = call(t, "GET", base+"/content?node_id="+old, nil, map[string]string{"Authorization": h["Authorization"]})
	requireStatus(t, s, 200, b)
	if string(b) != "new" {
		t.Fatal("stale upload overwrote newer content")
	}
	s, b = call(t, "DELETE", base+"/uploads/"+upload, nil, h)
	requireStatus(t, s, 204, b)
	s, b = call(t, "POST", base+"/uploads/"+upload+"/finalize", nil, h)
	requireStatus(t, s, 409, b)
	// Go must preserve JSON text escapes so Rust can reject unpaired surrogates.
	raw := []byte(fmt.Sprintf(`{"parent":{"node_id":%q},"name":"invalid","text":"\ud800"}`, root))
	s, b = rawCall(t, "POST", base+"/text", raw, map[string]string{"Authorization": "Bearer " + jwt, "Content-Type": "application/json"})
	requireStatus(t, s, 400, b)
	var value any
	if !json.Valid(b) || json.Unmarshal(b, &value) != nil {
		t.Fatal("invalid error envelope")
	}
}

func TestStorageMultipartUploads(t *testing.T) {
	jwt, _, ws := onboard(t, "multipart_"+uuid.NewString(), uuid.NewString()+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	data := bytes.Repeat([]byte{'m'}, 17*1024*1024)
	h["Idempotency-Key"] = uuid.NewString()
	metadata := map[string]any{"parent": map[string]string{"node_id": root}, "name": "multipart.bin", "storage": "object", "size_bytes": fmt.Sprint(len(data))}
	s, b = call(t, "POST", base+"/uploads", metadata, h)
	requireStatus(t, s, 201, b)
	upload := jsonMap(t, b)
	id := upload["id"].(string)
	if upload["transport"] != "multipart" {
		t.Fatal("expected native multipart", string(b))
	}
	partSize := 8 * 1024 * 1024
	var checksums []any
	for offset := 0; offset < len(data); offset += partSize {
		sum := md5.Sum(data[offset:min(offset+partSize, len(data))])
		checksums = append(checksums, map[string]any{"part_number": len(checksums) + 1, "content_md5": base64.StdEncoding.EncodeToString(sum[:])})
	}
	db := serviceDB(t, "letfs")
	count := func() int64 {
		var n int64
		if e := db.QueryRow(t.Context(), "SELECT coalesce(sum(calls),0)::bigint FROM pg_stat_statements WHERE dbid=(SELECT oid FROM pg_database WHERE datname=current_database()) AND query LIKE 'SELECT * FROM uploads WHERE id=%'").Scan(&n); e != nil {
			t.Fatal(e)
		}
		return n
	}
	var parts []any
	for _, requested := range [][]any{checksums[:1], checksums} {
		before := count()
		s, b = call(t, "POST", base+"/uploads/"+id+"/parts", map[string]any{"parts": requested}, h)
		requireStatus(t, s, 200, b)
		parts = jsonMap(t, b)["items"].([]any)
		if len(parts) != len(requested) || count()-before != 1 {
			t.Fatal("part signing must load the upload once per batch", string(b))
		}
	}
	var receipts []any
	for i, part := range parts {
		descriptor := part.(map[string]any)["transfer"].(map[string]any)
		request, e := http.NewRequest(http.MethodPut, descriptor["url"].(string), bytes.NewReader(data[i*partSize:min((i+1)*partSize, len(data))]))
		if e != nil {
			t.Fatal(e)
		}
		for k, v := range descriptor["headers"].(map[string]any) {
			request.Header.Set(k, v.(string))
		}
		response, e := client.Do(request)
		if e != nil {
			t.Fatal(e)
		}
		body, e := io.ReadAll(response.Body)
		response.Body.Close()
		if e != nil || response.StatusCode != 200 {
			t.Fatalf("direct part upload: status=%d error=%v body=%s", response.StatusCode, e, body)
		}
		receipts = append(receipts, map[string]any{"part_number": i + 1, "etag": response.Header.Get("ETag")})
	}
	// The provider commits, then the fault boundary replaces its reply with 503.
	s, b = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{"lose_complete": 1}, nil)
	requireStatus(t, s, 204, b)
	t.Cleanup(func() {
		status, body := call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{}, nil)
		requireStatus(t, status, 204, body)
	})
	s, b = call(t, "POST", base+"/uploads/"+id+"/finalize", map[string]any{"parts": receipts}, h)
	requireStatus(t, s, 200, b)
	result := jsonMap(t, b)
	s, b = call(t, "POST", base+"/uploads/"+id+"/finalize", nil, h)
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["node_id"] != result["node_id"] {
		t.Fatal("completion retry duplicated publication")
	}
	s, b = call(t, "GET", base+"/content?node_id="+result["node_id"].(string), nil, h)
	requireStatus(t, s, 200, b)
	if !bytes.Equal(b, data) {
		t.Fatal("multipart recovery changed bytes")
	}
	receipts[0].(map[string]any)["etag"] = "\"00000000000000000000000000000000\""
	s, b = call(t, "POST", base+"/uploads/"+id+"/finalize", map[string]any{"parts": receipts}, h)
	requireStatus(t, s, 409, b)
}

func waitFileOperation(t *testing.T, statusURL string, h map[string]string) string {
	t.Helper()
	deadline := time.Now().Add(40 * time.Second)
	for {
		s, b := call(t, "GET", "http://envoy:8080"+statusURL, nil, h)
		requireStatus(t, s, 200, b)
		op := jsonMap(t, b)
		if op["state"] == "succeeded" {
			return op["node_id"].(string)
		}
		if op["state"] == "failed" || time.Now().After(deadline) {
			t.Fatal("copy failed or timed out", string(b))
		}
		time.Sleep(50 * time.Millisecond)
	}
}

func waitOperation(t *testing.T, url string, h map[string]string) map[string]any {
	t.Helper()
	deadline := time.Now().Add(45 * time.Second)
	for time.Now().Before(deadline) {
		s, b := call(t, "GET", "http://envoy:8080"+url, nil, h)
		requireStatus(t, s, 200, b)
		v := jsonMap(t, b)
		if v["state"] == "succeeded" {
			return v
		}
		if v["state"] == "failed" {
			t.Fatal("operation failed", string(b))
		}
		time.Sleep(20 * time.Millisecond)
	}
	t.Fatal("operation did not finish")
	return nil
}

func prepareUpload(t *testing.T, base string, in map[string]any, data []byte, mode string, h map[string]string) map[string]any {
	t.Helper()
	in["storage"] = mode
	in["size_bytes"] = fmt.Sprint(len(data))
	if mode == "object" {
		sum := md5.Sum(data)
		in["content_md5"] = base64.StdEncoding.EncodeToString(sum[:])
	}
	headers := map[string]string{}
	for k, v := range h {
		headers[k] = v
	}
	headers["Idempotency-Key"] = uuid.NewString()
	status, body := call(t, "POST", base+"/uploads", in, headers)
	requireStatus(t, status, 201, body)
	return jsonMap(t, body)
}
func transferUpload(t *testing.T, base string, prepared map[string]any, data []byte, h map[string]string) {
	t.Helper()
	if prepared["transport"] == "inline" {
		status, body := rawCall(t, "PUT", base+"/uploads/"+prepared["id"].(string)+"/bytes", data, h)
		requireStatus(t, status, 200, body)
		return
	}
	descriptor := prepared["transfer"].(map[string]any)
	request, e := http.NewRequest(http.MethodPut, descriptor["url"].(string), bytes.NewReader(data))
	if e != nil {
		t.Fatal(e)
	}
	for k, v := range descriptor["headers"].(map[string]any) {
		request.Header.Set(k, v.(string))
	}
	response, e := client.Do(request)
	if e != nil {
		t.Fatal(e)
	}
	defer response.Body.Close()
	body, e := io.ReadAll(response.Body)
	if e != nil {
		t.Fatal(e)
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		t.Fatalf("direct PUT status=%d: %s", response.StatusCode, body)
	}
}
