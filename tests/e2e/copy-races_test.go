package e2e

import (
	"fmt"
	"github.com/google/uuid"
	"testing"
	"time"
)

func TestStorageCopyRaces(t *testing.T) {
	for _, kind := range []string{"source-change", "source-move", "source-trash", "quota-publication"} {
		t.Run(kind, func(t *testing.T) {
			suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
			jwt, actor, ws := onboard(t, "user_copy_race_"+suffix, "copy-race-"+suffix+"@example.test", uuid.NewString(), 0)
			base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
			h := map[string]string{"Authorization": "Bearer " + jwt}
			s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
			requireStatus(t, s, 200, b)
			root := jsonMap(t, b)["id"].(string)
			parent := map[string]string{"node_id": root}
			content := []byte{0, 1, 2, 3}
			prepared := prepareUpload(t, base, map[string]any{"parent": parent, "name": "source"}, content, "object", h)
			upload := prepared["id"].(string)
			transferUpload(t, base, prepared, content, h)
			s, b = call(t, "POST", base+"/uploads/"+upload+"/finalize", nil, h)
			requireStatus(t, s, 200, b)
			source := jsonMap(t, b)["node_id"].(string)
			s, b = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{"block_copy": true}, nil)
			requireStatus(t, s, 204, b)
			t.Cleanup(func() {
				s, b := call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{}, nil)
				requireStatus(t, s, 204, b)
			})
			key := uuid.NewString()
			h["If-Match"] = "\"1\""
			h["Idempotency-Key"] = key
			s, b = call(t, "POST", base+"/copy", map[string]any{"locator": map[string]string{"node_id": source}, "parent": parent, "name": "destination"}, h)
			requireStatus(t, s, 202, b)
			op := jsonMap(t, b)
			url := op["status_url"].(string)
			deadline := time.Now().Add(15 * time.Second)
			for {
				s, b = call(t, "GET", "http://issuer:8080/control/storage", nil, nil)
				requireStatus(t, s, 200, b)
				if jsonMap(t, b)["copy_seen"] == true {
					break
				}
				if time.Now().After(deadline) {
					t.Fatal("copy did not reach provider barrier")
				}
				time.Sleep(10 * time.Millisecond)
			}
			db := serviceDB(t, "letfs")
			fs := filesystemForNode(t, root)
			want := "SOURCE_CHANGED"
			used := int64(7)
			if kind == "source-change" {
				// This request succeeds while S3 copy is blocked, proving there is no DB lock held over I/O.
				s, b = call(t, "PUT", base+"/text", map[string]any{"locator": map[string]string{"node_id": source}, "text": "changed"}, h)
				requireStatus(t, s, 200, b)
			} else if kind == "source-move" {
				s, b = call(t, "POST", base+"/directories", map[string]any{"parent": parent, "name": "moved-into"}, h)
				requireStatus(t, s, 201, b)
				destination := jsonMap(t, b)["id"].(string)
				s, b = call(t, "POST", base+"/move", map[string]any{"locator": map[string]string{"node_id": source}, "parent": map[string]string{"node_id": destination}}, h)
				requireStatus(t, s, 200, b)
				used = 4
			} else if kind == "source-trash" {
				s, b = call(t, "POST", base+"/trash", map[string]any{"locator": map[string]string{"node_id": source}}, h)
				requireStatus(t, s, 200, b)
				used = 4
			} else {
				want = "QUOTA_EXCEEDED"
				used = 4
				if _, e := db.Exec(t.Context(), "UPDATE quota_buckets SET limit_bytes=used_bytes WHERE id=(SELECT bucket_id FROM filesystems WHERE id=$1)", fs); e != nil {
					t.Fatal(e)
				}
			}
			s, b = call(t, "PUT", "http://issuer:8080/control/storage", map[string]any{}, nil)
			requireStatus(t, s, 204, b)
			for {
				s, b = call(t, "GET", "http://envoy:8080"+url, nil, h)
				requireStatus(t, s, 200, b)
				state := jsonMap(t, b)
				if state["state"] == "failed" {
					if state["error_code"] != want {
						t.Fatal("wrong terminal error", string(b))
					}
					break
				}
				if time.Now().After(deadline) {
					t.Fatal("copy failure did not clean staging", string(b))
				}
				time.Sleep(20 * time.Millisecond)
			}
			var actual, staged int64
			if e := db.QueryRow(t.Context(), "SELECT used_bytes FROM quota_buckets WHERE id=(SELECT bucket_id FROM filesystems WHERE id=$1)", fs).Scan(&actual); e != nil || actual != used {
				t.Fatal("copy charged failed publication", actual, used, e)
			}
			if e := db.QueryRow(t.Context(), "SELECT count(*) FROM nodes WHERE staging_operation_id=$1", op["operation_id"]).Scan(&staged); e != nil || staged != 0 {
				t.Fatal("staging survived", staged, e)
			}
			s, b = call(t, "GET", base+"/stat?path=/drive/destination", nil, h)
			requireStatus(t, s, 404, b)
			saveHistory(t, "copy/"+fs+"/"+actor+"/"+key, "CopyNodeFailed")
		})
	}
}

func TestStorageCopyBounds(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, _, ws := onboard(t, "user_copy_bounds_"+suffix, "copy-bounds-"+suffix+"@example.test", uuid.NewString(), 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	parent := map[string]string{"node_id": root}
	s, b = call(t, "POST", base+"/directories", map[string]any{"parent": parent, "name": "bounded"}, h)
	requireStatus(t, s, 201, b)
	dir := jsonMap(t, b)["id"].(string)
	fs := filesystemForNode(t, root)
	h["If-Match"] = "\"1\""
	h["Idempotency-Key"] = uuid.NewString()
	s, b = call(t, "POST", base+"/copy", map[string]any{"locator": map[string]string{"node_id": dir}, "parent": map[string]string{"node_id": dir}, "name": "recursive"}, h)
	requireStatus(t, s, 409, b)
	db := serviceDB(t, "letfs")
	if _, e := db.Exec(t.Context(), "WITH added AS (INSERT INTO nodes(id,filesystem_id,parent_id,name,kind) SELECT uuidv7(),$1,$2,'child-'||i,'directory' FROM generate_series(1,70) i RETURNING id) UPDATE filesystems SET node_count=node_count+(SELECT count(*) FROM added) WHERE id=$1", fs, dir); e != nil {
		t.Fatal(e)
	}
	h["Idempotency-Key"] = uuid.NewString()
	s, b = call(t, "POST", base+"/copy", map[string]any{"locator": map[string]string{"node_id": dir}, "parent": parent, "name": "must-not-publish"}, h)
	requireStatus(t, s, 202, b)
	op := jsonMap(t, b)
	deadline := time.Now().Add(15 * time.Second)
	for {
		s, b = call(t, "GET", "http://envoy:8080"+op["status_url"].(string), nil, h)
		requireStatus(t, s, 200, b)
		v := jsonMap(t, b)
		if v["state"] == "failed" {
			if v["error_code"] != "RESOURCE_LIMIT" {
				t.Fatal(string(b))
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("copy ceiling did not terminate", string(b))
		}
		time.Sleep(10 * time.Millisecond)
	}
	var count int
	if e := db.QueryRow(t.Context(), "SELECT count(*) FROM nodes WHERE staging_operation_id=$1", op["operation_id"]).Scan(&count); e != nil || count != 0 {
		t.Fatal("bounded copy leaked staging", count, e)
	}
}
