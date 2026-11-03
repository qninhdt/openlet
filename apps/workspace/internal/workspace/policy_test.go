package workspace

import (
	"errors"
	"github.com/google/uuid"
	"testing"
)

func TestWorkspaceActiveLifecycle(t *testing.T) {
	for _, c := range []struct{ state, code string }{
		{"active", ""}, {"provisioning", "WORKSPACE_DELETING"}, {"failed", "WORKSPACE_DELETING"}, {"deleting", "WORKSPACE_DELETING"}, {"deleted", "NOT_FOUND"},
	} {
		var want error
		if c.code != "" {
			want = Fault{c.code}
		}
		if err := (Workspace{Status: c.state}).checkActive(); !errors.Is(err, want) {
			t.Fatalf("%s: got %v want %v", c.state, err, want)
		}
	}
}

func TestNormalizeEmail(t *testing.T) {
	for _, v := range []string{"Name <a@example.test>", "a@example.test\r\nBcc:x@example.test", "not-an-email"} {
		if _, e := NormalizeEmail(v); e == nil {
			t.Errorf("accepted %q", v)
		}
	}
	v, e := NormalizeEmail("  A+B@Example.Test  ")
	if e != nil || v != "a+b@example.test" {
		t.Fatal(v, e)
	}
}
func TestFingerprintBindsOriginalInput(t *testing.T) {
	a := CreateInput{ActorID: uuid.Must(uuid.NewV7()), Key: uuid.Must(uuid.NewV7()), Name: "name"}
	b := a
	if Fingerprint(a) != Fingerprint(b) {
		t.Fatal("unstable fingerprint")
	}
	b.Name = "another"
	if Fingerprint(a) == Fingerprint(b) {
		t.Fatal("name not bound")
	}
	b = a
	b.ActorID = uuid.Must(uuid.NewV7())
	if Fingerprint(a) == Fingerprint(b) {
		t.Fatal("caller not bound")
	}
}
