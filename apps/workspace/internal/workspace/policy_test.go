package workspace

import (
	"errors"
	"github.com/google/uuid"
	"testing"
)

func TestWorkspaceAccess(t *testing.T) {
	for _, c := range []struct {
		role, minimum, state, code string
	}{
		{"owner", "owner", "active", ""},
		{"owner", "editor", "active", ""},
		{"owner", "viewer", "active", ""},
		{"editor", "owner", "active", "FORBIDDEN"},
		{"editor", "editor", "active", ""},
		{"editor", "viewer", "active", ""},
		{"viewer", "owner", "active", "FORBIDDEN"},
		{"viewer", "editor", "active", "FORBIDDEN"},
		{"viewer", "viewer", "active", ""},
		{"owner", "viewer", "provisioning", "WORKSPACE_DELETING"},
		{"owner", "viewer", "deleting", "WORKSPACE_DELETING"},
		{"owner", "viewer", "deleted", "NOT_FOUND"},
		{"viewer", "owner", "deleting", "WORKSPACE_DELETING"},
	} {
		t.Run(c.role+"/"+c.minimum+"/"+c.state, func(t *testing.T) {
			var want error
			if c.code != "" {
				want = Fault{c.code}
			}
			err := (Workspace{Status: c.state, Role: c.role}).checkAccess(c.minimum)
			if !errors.Is(err, want) {
				t.Fatalf("got %v; want %v", err, want)
			}
		})
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
