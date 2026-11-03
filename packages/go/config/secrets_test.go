package config

import (
	"os"
	"path/filepath"
	"testing"
)

func TestSecret(t *testing.T) {
	path := filepath.Join(t.TempDir(), "value")
	if err := os.WriteFile(path, []byte("  file-value\n"), 0600); err != nil {
		t.Fatal(err)
	}
	for _, test := range []struct {
		name, direct, file, want string
	}{
		{"absent", "", "", ""},
		{"environment", " direct-value ", "", " direct-value "},
		{"file precedence", "direct-value", path, "file-value"},
		{"unreadable file", "direct-value", path + ".missing", ""},
	} {
		t.Run(test.name, func(t *testing.T) {
			t.Setenv("OPENLET_TEST_SECRET", test.direct)
			t.Setenv("OPENLET_TEST_SECRET_FILE", test.file)
			if got := Secret("OPENLET_TEST_SECRET"); got != test.want {
				t.Fatalf("Secret returned %q, want %q", got, test.want)
			}
		})
	}
}
