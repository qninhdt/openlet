package e2e

import (
	"bytes"
	"fmt"
	"image/png"
	"net/url"
	"os"
	"regexp"
	"strings"
	"testing"
	"time"
)

func TestProcessing(t *testing.T) {
	suffix := fmt.Sprintf("%012x", time.Now().UnixNano()&0xffffffffffff)
	jwt, _, ws := onboard(t, "user_processing_"+suffix, "processing-"+suffix+"@example.test", "019ad06b-7d00-7000-9500-"+suffix, 0)
	base := "http://envoy:8080/v1/workspaces/" + ws + "/files"
	h := map[string]string{"Authorization": "Bearer " + jwt}
	s, b := call(t, "GET", base+"/stat?path=/drive", nil, h)
	requireStatus(t, s, 200, b)
	root := jsonMap(t, b)["id"].(string)
	for _, kind := range []string{"pdf", "docx", "pptx", "xlsx"} {
		t.Run(kind, func(t *testing.T) {
			original, err := os.ReadFile("/processing-fixtures/tiny." + kind)
			if err != nil {
				t.Fatal(err)
			}
			mode := "object"
			if kind == "docx" {
				mode = "inline"
			}
			name := "tiny." + kind
			prepared := prepareUpload(t, base, map[string]any{"parent": map[string]string{"node_id": root}, "name": name}, original, mode, h)
			transferUpload(t, base, prepared, original, h)
			s, b = call(t, "POST", base+"/uploads/"+prepared["id"].(string)+"/finalize", map[string]any{}, h)
			requireStatus(t, s, 200, b)
			node := jsonMap(t, b)["node_id"].(string)
			statusURL := base + "/processing-status?node_id=" + node
			var operation string
			deadline := time.Now().Add(150 * time.Second)
			for {
				s, b = call(t, "GET", statusURL, nil, h)
				requireStatus(t, s, 200, b)
				status := jsonMap(t, b)
				operation = status["operation_id"].(string)
				if processingStage(t, status, "index")["state"] == "succeeded" {
					break
				}
				if processingStage(t, status, "parse")["state"] == "failed" || processingStage(t, status, "enrichment")["state"] == "failed" || processingStage(t, status, "index")["state"] == "failed" || time.Now().After(deadline) {
					t.Fatalf("processing failed or timed out: %s", b)
				}
				time.Sleep(100 * time.Millisecond)
			}
			s, b = call(t, "GET", base+"/content?node_id="+node, nil, h)
			requireStatus(t, s, 200, b)
			if !bytes.Equal(b, original) {
				t.Fatal("processing changed original bytes")
			}
			expected := map[string]string{
				"pdf": "README.md", "docx": "README.md",
				"pptx": "README.md", "xlsx": "1-untitled/README.md",
			}[kind]
			path := "/drive/" + name + "/" + expected
			s, b = call(t, "GET", base+"/content?path="+url.QueryEscape(path), nil, h)
			requireStatus(t, s, 200, b)
			needle := map[string]string{"pdf": "Hello PDF.", "docx": "Hello document.", "pptx": "Hello slides.", "xlsx": "=1+2"}[kind]
			if !strings.Contains(string(b), needle) {
				t.Fatalf("missing converted content: %q", b)
			}
			s, b = call(t, "GET", base+"/stat?path="+url.QueryEscape(path), nil, h)
			requireStatus(t, s, 200, b)
			child := jsonMap(t, b)
			writeHeaders := map[string]string{"Authorization": "Bearer " + jwt, "If-Match": fmt.Sprintf("\"%v\"", child["revision"])}
			s, b = call(t, "PUT", base+"/text", map[string]any{"locator": map[string]any{"node_id": child["id"]}, "text": "changed"}, writeHeaders)
			requireStatus(t, s, 403, b)
			saveHistory(t, "process-file/"+operation, "ProcessFile"+strings.ToUpper(kind[:1])+kind[1:])
			if kind == "docx" {
				s, b = call(t, "GET", base+"/stat?node_id="+node, nil, h)
				requireStatus(t, s, 200, b)
				copyHeaders := map[string]string{"Authorization": h["Authorization"], "If-Match": fmt.Sprintf("\"%v\"", jsonMap(t, b)["revision"]), "Idempotency-Key": "019ad06b-7d00-7000-9600-" + suffix}
				s, b = call(t, "POST", base+"/copy", map[string]any{"locator": map[string]string{"node_id": node}, "parent": map[string]string{"node_id": root}, "name": "copied.docx"}, copyHeaders)
				requireStatus(t, s, 202, b)
				copied := waitFileOperation(t, jsonMap(t, b)["status_url"].(string), h)
				copiedOp := waitSearchReady(t, base, copied, h)
				var generation int
				if err := serviceDB(t, "letfs").QueryRow(t.Context(), "SELECT attempt_generation FROM operations WHERE id=$1", copiedOp).Scan(&generation); err != nil || generation != 0 {
					t.Fatal("copied artifact tree was reparsed", generation, err)
				}
				s, b = call(t, "GET", base+"/content?path=/drive/copied.docx/README.md", nil, h)
				requireStatus(t, s, 200, b)
				if !strings.Contains(string(b), "Hello document.") || !strings.Contains(string(b), "Done.") {
					t.Fatal("copied tree lost content", string(b))
				}
			}
			if kind == "pdf" {
				saveHistory(t, "process-file/"+operation, "ProcessFile")
			}
		})
	}
	t.Run("embedded-image", func(t *testing.T) {
		original, err := os.ReadFile("/processing-fixtures/image.docx")
		if err != nil {
			t.Fatal(err)
		}
		prepared := prepareUpload(t, base, map[string]any{"parent": map[string]string{"node_id": root}, "name": "image.docx"}, original, "object", h)
		transferUpload(t, base, prepared, original, h)
		s, b = call(t, "POST", base+"/uploads/"+prepared["id"].(string)+"/finalize", nil, h)
		requireStatus(t, s, 200, b)
		id := jsonMap(t, b)["node_id"].(string)
		deadline := time.Now().Add(90 * time.Second)
		for {
			s, b = call(t, "GET", base+"/processing-status?node_id="+id, nil, h)
			requireStatus(t, s, 200, b)
			state := processingStage(t, jsonMap(t, b), "index")["state"]
			if state == "succeeded" {
				break
			}
			if state == "failed" || time.Now().After(deadline) {
				t.Fatalf("image processing: %s", b)
			}
			time.Sleep(100 * time.Millisecond)
		}
		s, b = call(t, "GET", base+"/content?path=/drive/image.docx/README.md", nil, h)
		requireStatus(t, s, 200, b)
		markdown := string(b)
		if strings.HasPrefix(markdown, "---\n") {
			parts := strings.SplitN(markdown, "\n---\n", 2)
			if len(parts) != 2 {
				t.Fatal("invalid README frontmatter")
			}
			markdown = parts[1]
		}
		s, b = call(t, "GET", base+"/list?path=/drive/image.docx", nil, h)
		requireStatus(t, s, 200, b)
		all := jsonMap(t, b)["items"].([]any)
		items := []any{}
		for _, item := range all {
			if strings.HasSuffix(item.(map[string]any)["name"].(string), ".png") {
				items = append(items, item)
			}
		}
		if len(items) != 1 {
			t.Fatal("expected one extracted image", string(b))
		}
		entry := items[0].(map[string]any)
		links := regexp.MustCompile(`!\[[^\]]*\]\(([^)]+)\)`).FindAllStringSubmatch(markdown, -1)
		if len(links) != 1 || links[0][1] != entry["name"].(string) {
			t.Fatal("markdown image reference must resolve relative to its file", markdown)
		}
		s, b = call(t, "GET", base+"/content?path="+url.QueryEscape("/drive/image.docx/"+links[0][1]), nil, h)
		requireStatus(t, s, 200, b)
		output, err := png.Decode(bytes.NewReader(b))
		if err != nil {
			t.Fatal(err)
		}
		source, err := os.ReadFile("/processing-fixtures/image.png")
		if err != nil {
			t.Fatal(err)
		}
		image, err := png.Decode(bytes.NewReader(source))
		if err != nil {
			t.Fatal(err)
		}
		if output.Bounds() != image.Bounds() {
			t.Fatal("image dimensions changed")
		}
		for y := image.Bounds().Min.Y; y < image.Bounds().Max.Y; y++ {
			for x := image.Bounds().Min.X; x < image.Bounds().Max.X; x++ {
				r, g, b, a := image.At(x, y).RGBA()
				rr, gg, bb, aa := output.At(x, y).RGBA()
				if r != rr || g != gg || b != bb || a != aa {
					t.Fatal("image pixels changed")
				}
			}
		}
	})
	for _, name := range []string{"image.png", "note.txt", "legacy.doc"} {
		t.Run("bypass-"+name, func(t *testing.T) {
			original, err := os.ReadFile("/processing-fixtures/" + name)
			if err != nil {
				t.Fatal(err)
			}
			prepared := prepareUpload(t, base, map[string]any{"parent": map[string]string{"node_id": root}, "name": name}, original, "object", h)
			transferUpload(t, base, prepared, original, h)
			s, b = call(t, "POST", base+"/uploads/"+prepared["id"].(string)+"/finalize", nil, h)
			requireStatus(t, s, 200, b)
			id := jsonMap(t, b)["node_id"].(string)
			s, b = call(t, "GET", base+"/processing-status?node_id="+id, nil, h)
			if name == "legacy.doc" {
				requireStatus(t, s, 404, b)
			} else {
				requireStatus(t, s, 200, b)
				if processingStage(t, jsonMap(t, b), "parse")["state"] != "succeeded" {
					t.Fatal("direct source scheduled parsing", string(b))
				}
			}
			s, b = call(t, "GET", base+"/content?node_id="+id, nil, h)
			requireStatus(t, s, 200, b)
			if !bytes.Equal(b, original) {
				t.Fatal("bypass changed original bytes")
			}
		})
	}
}

func processingStage(t *testing.T, status map[string]any, stage string) map[string]any {
	t.Helper()
	stages, ok := status["stages"].(map[string]any)
	if !ok {
		t.Fatalf("missing processing stages: %#v", status)
	}
	value, ok := stages[stage].(map[string]any)
	if !ok {
		t.Fatalf("missing processing stage %s: %#v", stage, status)
	}
	return value
}
