package sdk

import (
	"os"
	"path/filepath"
	"testing"
)

func TestRoleConfigAndSecrets(t *testing.T) {
	p := filepath.Join(t.TempDir(), "openlet.yaml")
	err := os.WriteFile(p, []byte("mine:\n  key: ${TEST_SECRET}\nother:\n  key: ${UNSET_OTHER_ROLE}\n"), 0600)
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("OPENLET_CONFIG", p)
	t.Setenv("TEST_SECRET", "a: b\n$quoted")
	c, err := LoadConfig()
	if err != nil {
		t.Fatal(err)
	}
	var s struct {
		Key string `yaml:"key"`
	}
	if err = c.Section("mine", &s); err != nil {
		t.Fatal(err)
	}
	v, err := Secret("mine.key", s.Key)
	if err != nil || v != "a: b\n$quoted" {
		t.Fatalf("value=%q error=%v", v, err)
	}
	if _, err = Secret("other.key", "${UNSET_OTHER_ROLE}"); err == nil {
		t.Fatal("missing required secret accepted")
	}
}
