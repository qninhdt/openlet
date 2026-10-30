package e2e

import (
	"encoding/json"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

var contractLock sync.Mutex

func recordContract(t *testing.T, method, address string, status int, body []byte) {
	t.Helper()
	directory := os.Getenv("OPENLET_CONTRACT_DIR")
	if directory == "" {
		return
	}
	parsed, e := url.Parse(address)
	if e != nil || parsed.Host != "envoy:8080" || strings.HasSuffix(parsed.Path, "/content") {
		return
	}
	var value any
	if len(body) > 0 {
		if !json.Valid(body) {
			return
		}
		if e = json.Unmarshal(body, &value); e != nil {
			t.Fatal(e)
		}
	}
	// Persist generated response shapes only; discard the one-time invitation credential.
	if m, ok := value.(map[string]any); ok {
		if _, exists := m["token"]; exists {
			m["token"] = strings.Repeat("r", 43)
		}
	}
	raw, e := json.Marshal(map[string]any{"method": method, "path": parsed.Path, "status": status, "body": value})
	if e != nil {
		t.Fatal(e)
	}
	contractLock.Lock()
	defer contractLock.Unlock()
	if e = os.MkdirAll(directory, 0700); e != nil {
		t.Fatal(e)
	}
	f, e := os.OpenFile(filepath.Join(directory, "responses.jsonl"), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0600)
	if e != nil {
		t.Fatal(e)
	}
	defer f.Close()
	if _, e = f.Write(append(raw, '\n')); e != nil {
		t.Fatal(e)
	}
}
