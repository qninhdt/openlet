package e2e

import (
	"fmt"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"
)

func waitSearchReady(t *testing.T, base, id string, h map[string]string) string {
	t.Helper()
	deadline := time.Now().Add(150 * time.Second)
	for {
		s, b := call(t, "GET", base+"/processing-status?node_id="+id, nil, h)
		requireStatus(t, s, 200, b)
		status := jsonMap(t, b)
		if processingStage(t, status, "index")["state"] == "succeeded" {
			return status["operation_id"].(string)
		}
		for _, stage := range []string{"parse", "enrichment", "index"} {
			if processingStage(t, status, stage)["state"] == "failed" {
				t.Fatalf("%s failed: %s", stage, b)
			}
		}
		if time.Now().After(deadline) {
			t.Fatalf("search readiness timeout: %s", b)
		}
		time.Sleep(100 * time.Millisecond)
	}
}
func TestProcessingSearch(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, _, ws := onboard(t, "user_search_"+suffix, "search-"+suffix+"@example.test", "019ad06b-7d00-7000-9500-"+suffix, 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	s, b = call(t, "POST", base+"/text", map[string]any{"parent": map[string]string{"node_id": root}, "name": "before-ai.txt", "text": "Vietnamese notes: nghiên cứu núi lửa."}, h)
	requireStatus(t, s, 201, b)
	small := jsonMap(t, b)["id"].(string)
	s, b = call(t, "GET", base+"/search?query=before-ai", nil, h)
	requireStatus(t, s, 200, b)
	if items := jsonMap(t, b)["items"].([]any); len(items) != 1 || items[0].(map[string]any)["node_id"] != small {
		t.Fatal("basic search missed newly created text", string(b))
	}
	marker := "rarevolcanofinding" + suffix
	original := []byte(strings.Repeat("ordinary preamble filler. ", 7000) + marker + " detailed observation. " + strings.Repeat("ordinary closing filler. ", 5000))
	prepared := prepareUpload(t, base, map[string]any{"parent": map[string]string{"node_id": root}, "name": "research.txt"}, original, "object", h)
	transferUpload(t, base, prepared, original, h)
	s, b = call(t, "POST", base+"/uploads/"+prepared["id"].(string)+"/finalize", nil, h)
	requireStatus(t, s, 200, b)
	source := jsonMap(t, b)["node_id"].(string)
	op := waitSearchReady(t, base, source, h)
	waitSearchReady(t, base, small, h)
	image, err := os.ReadFile("/processing-fixtures/image.png")
	if err != nil {
		t.Fatal(err)
	}
	for _, direct := range []struct {
		name, mime string
		bytes      []byte
	}{
		{"measurements.csv", "text/csv", []byte("place,reading\nvolcano,12\n")},
		{"direct-image.png", "image/png", image},
	} {
		prepared := prepareUpload(t, base, map[string]any{"parent": map[string]string{"node_id": root}, "name": direct.name}, direct.bytes, "object", h)
		transferUpload(t, base, prepared, direct.bytes, h)
		s, b = call(t, "POST", base+"/uploads/"+prepared["id"].(string)+"/finalize", nil, h)
		requireStatus(t, s, 200, b)
		id := jsonMap(t, b)["node_id"].(string)
		waitSearchReady(t, base, id, h)
		s, b = call(t, "GET", base+"/stat?node_id="+id, nil, h)
		requireStatus(t, s, 200, b)
		if jsonMap(t, b)["media_type"] != direct.mime || jsonMap(t, b)["title"] == nil {
			t.Fatal("missing direct source metadata", string(b))
		}
		s, b = call(t, "GET", base+"/list?node_id="+id, nil, h)
		requireStatus(t, s, 200, b)
		if len(jsonMap(t, b)["items"].([]any)) != 0 {
			t.Fatal("direct source created artifacts", string(b))
		}
	}
	s, b = call(t, "GET", base+"/stat?node_id="+source, nil, h)
	requireStatus(t, s, 200, b)
	if context, _ := jsonMap(t, b)["context"].(string); strings.Contains(context, marker) {
		t.Fatal("fixture evidence unexpectedly appeared in enrichment sample")
	}
	search := func() map[string]any {
		s, b = call(t, "POST", base+"/semantic-search", map[string]any{"query": marker}, h)
		requireStatus(t, s, 200, b)
		return jsonMap(t, b)
	}
	result := search()
	items := result["items"].([]any)
	found := false
	for _, item := range items {
		v := item.(map[string]any)
		if v["node_id"] == source {
			found = true
			m := v["matched"].(map[string]any)
			if m["file_id"] != source || len(m["breadcrumb"].([]any)) != 1 || !strings.Contains(m["snippet"].(string), marker) {
				t.Fatal("missing matched source evidence", v)
			}
		}
	}
	if !found {
		t.Fatal("full text outside enrichment evidence was not indexed", result)
	}
	s, b = call(t, "POST", base+"/semantic-search", map[string]any{"query": "nghiên cứu núi lửa"}, h)
	requireStatus(t, s, 200, b)
	found = false
	for _, item := range jsonMap(t, b)["items"].([]any) {
		v := item.(map[string]any)
		if v["node_id"] == small && strings.Contains(v["matched"].(map[string]any)["snippet"].(string), "nghiên cứu núi lửa") {
			found = true
		}
	}
	if !found {
		t.Fatal("short Vietnamese text was not indexed", string(b))
	}
	s, b = call(t, "POST", "http://issuer:8080/ai-control", map[string]bool{"rerank": true}, nil)
	requireStatus(t, s, 204, b)
	if search()["degraded"] != true {
		t.Fatal("missing rerank degradation")
	}
	s, b = call(t, "POST", "http://issuer:8080/ai-control", map[string]bool{"embeddings": true}, nil)
	requireStatus(t, s, 204, b)
	s, b = call(t, "POST", base+"/semantic-search", map[string]any{"query": marker}, h)
	requireStatus(t, s, 503, b)
	s, b = call(t, "POST", "http://issuer:8080/ai-control", map[string]bool{}, nil)
	requireStatus(t, s, 204, b)
	s, b = call(t, "GET", base+"/stat?node_id="+source, nil, h)
	requireStatus(t, s, 200, b)
	revision := jsonMap(t, b)["revision"].(string)
	s, b = call(t, "POST", base+"/rename", map[string]any{"locator": map[string]string{"node_id": source}, "name": "renamed.txt"}, map[string]string{"Authorization": h["Authorization"], "If-Match": "\"" + revision + "\""})
	requireStatus(t, s, 200, b)
	s, b = call(t, "GET", base+"/search?query="+url.QueryEscape("renamed"), nil, h)
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["items"].([]any)[0].(map[string]any)["filename"] != "renamed.txt" {
		t.Fatal(string(b))
	}
	revision = jsonMap(t, b)["items"].([]any)[0].(map[string]any)["revision"].(string)
	s, b = call(t, "PUT", base+"/text", map[string]any{"locator": map[string]string{"node_id": source}, "text": "replacement has a different topic"}, map[string]string{"Authorization": h["Authorization"], "If-Match": "\"" + revision + "\""})
	requireStatus(t, s, 200, b)
	for _, item := range search()["items"].([]any) {
		if strings.Contains(item.(map[string]any)["matched"].(map[string]any)["snippet"].(string), marker) {
			t.Fatal("stale source evidence leaked")
		}
	}
	nextOp := waitSearchReady(t, base, source, h)
	if nextOp == op {
		t.Fatal("replacement reused previous content intent")
	}
	saveHistory(t, "process-file/"+op, "ProcessFileDirect")
	s, b = call(t, "POST", "http://issuer:8080/ai-control", map[string]bool{"embeddings": true}, nil)
	requireStatus(t, s, 204, b)
	s, b = call(t, "POST", base+"/text", map[string]any{"parent": map[string]string{"node_id": root}, "name": "retry-source.txt", "text": "retry preserves committed semantic enrichment"}, h)
	requireStatus(t, s, 201, b)
	retrySource := jsonMap(t, b)["id"].(string)
	deadline := time.Now().Add(60 * time.Second)
	var retryOp string
	for {
		s, b = call(t, "GET", base+"/processing-status?node_id="+retrySource, nil, h)
		requireStatus(t, s, 200, b)
		state := jsonMap(t, b)
		retryOp = state["operation_id"].(string)
		if processingStage(t, state, "index")["state"] == "failed" {
			if processingStage(t, state, "parse")["state"] != "succeeded" || processingStage(t, state, "enrichment")["state"] != "succeeded" {
				t.Fatal("index failure changed committed stages", string(b))
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("index did not reach terminal failure: %s", b)
		}
		time.Sleep(100 * time.Millisecond)
	}
	saveHistory(t, "process-file/"+retryOp, "ProcessFileIndexFailed")
	db := serviceDB(t, "letfs")
	var enrichedBefore, enrichedAfter time.Time
	if err := db.QueryRow(t.Context(), "SELECT enriched_at FROM operations WHERE id=$1", retryOp).Scan(&enrichedBefore); err != nil {
		t.Fatal(err)
	}
	s, b = call(t, "POST", "http://issuer:8080/ai-control", map[string]bool{}, nil)
	requireStatus(t, s, 204, b)
	s, b = call(t, "POST", base+"/processing-retry", map[string]any{"locator": map[string]string{"node_id": retrySource}, "stage": "index"}, h)
	requireStatus(t, s, 202, b)
	if waitSearchReady(t, base, retrySource, h) != retryOp {
		t.Fatal("index retry replaced the processing intent")
	}
	if err := db.QueryRow(t.Context(), "SELECT enriched_at FROM operations WHERE id=$1", retryOp).Scan(&enrichedAfter); err != nil {
		t.Fatal(err)
	}
	if !enrichedBefore.Equal(enrichedAfter) {
		t.Fatal("index retry reran enrichment")
	}
	saveHistory(t, "process-file/"+retryOp, "ProcessFileRebuild")
	s, b = call(t, "POST", base+"/processing-retry", map[string]any{"locator": map[string]string{"node_id": retrySource}, "stage": "index"}, h)
	requireStatus(t, s, 200, b)
	viewer, viewerID, _ := onboard(t, "user_search_viewer_"+suffix, "search-viewer-"+suffix+"@example.test", "019ad06b-7d00-7000-9400-"+suffix, 0)
	vh := map[string]string{"Authorization": "Bearer " + viewer}
	workspaceBase := strings.TrimSuffix(base, "/files")
	s, b = call(t, "POST", workspaceBase+"/invitations", map[string]string{"email": "search-viewer-" + suffix + "@example.test", "role": "viewer"}, h)
	requireStatus(t, s, 201, b)
	token := jsonMap(t, b)["token"].(string)
	s, b = call(t, "POST", "http://envoy:8080/v1/invitations/accept", map[string]string{"token": token}, vh)
	requireStatus(t, s, 200, b)
	s, b = call(t, "GET", base+"/search?query=.txt&media_type=text%2Fplain&limit=1", nil, vh)
	requireStatus(t, s, 200, b)
	page := jsonMap(t, b)
	cursor := page["next_cursor"].(string)
	firstID := page["items"].([]any)[0].(map[string]any)["node_id"]
	s, b = call(t, "GET", base+"/search?query=.txt&media_type=text%2Fplain&limit=1&cursor="+url.QueryEscape(cursor), nil, vh)
	requireStatus(t, s, 200, b)
	if jsonMap(t, b)["items"].([]any)[0].(map[string]any)["node_id"] == firstID {
		t.Fatal("filename cursor repeated an item")
	}
	s, b = call(t, "POST", base+"/semantic-search", map[string]any{"query": "notes", "filters": map[string]string{"media_type": "application/pdf"}}, vh)
	requireStatus(t, s, 200, b)
	if len(jsonMap(t, b)["items"].([]any)) != 0 {
		t.Fatal("media type filter was ignored", string(b))
	}
	s, b = call(t, "POST", base+"/processing-retry", map[string]any{"locator": map[string]string{"node_id": retrySource}, "stage": "index"}, vh)
	requireStatus(t, s, 403, b)
	s, b = call(t, "DELETE", workspaceBase+"/members/"+viewerID, nil, h)
	requireStatus(t, s, 204, b)
	s, b = call(t, "GET", base+"/search?query=.txt&media_type=text%2Fplain&limit=1&cursor="+url.QueryEscape(cursor), nil, vh)
	requireStatus(t, s, 404, b)
	s, b = call(t, "POST", base+"/semantic-search", map[string]any{"query": "notes"}, vh)
	requireStatus(t, s, 404, b)
}
