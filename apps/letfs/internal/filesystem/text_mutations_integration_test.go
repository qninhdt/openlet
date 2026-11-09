//go:build integration

package filesystem

import (
	"bytes"
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationTextMutations(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 64}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: actor, Service: "gateway", Gateway: true})
	fs, scope := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 1024})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{scope}, true, true)
	require.NoError(t, err)
	root := *scopes[0].RootID
	testfixture.Grant(t, graph, "scope", scope, actor, authz.ScopeWrite)
	creation := TextTarget{Create: &TextCreation{Key: uuid.New(), Parent: Locator{Path: ptr("/"), ExpectedParentID: &root, RootID: &root}, Name: "notes.bin", MediaType: "text/plain"}}
	created, err := s.WriteText(ctx, scope, creation, []byte("a a\r\nchào"))
	require.NoError(t, err)
	require.Equal(t, "text", created.Stat.StorageKind, "native creation explicitly stores text even for unknown/binary extension")
	require.Zero(t, created.BeforeRevision)
	replayed, err := s.WriteText(ctx, scope, creation, []byte("a a\r\nchào"))
	require.NoError(t, err)
	require.Equal(t, created, replayed)
	id := created.Stat.Node.ID
	target := TextTarget{Locator: Locator{Path: ptr("/notes.bin"), ExpectedNodeID: &id, RootID: &root}, Revision: created.Stat.Node.Revision, Fingerprint: &created.Stat.Fingerprint}
	var generation int64
	require.NoError(t, db.QueryRow(ctx, `SELECT desired_generation FROM files WHERE node_id=$1`, id).Scan(&generation))
	for _, tc := range []struct {
		name, code string
		edit       func() (TextMutationResult, error)
	}{
		{"ambiguous literal", "AMBIGUOUS_MATCH", func() (TextMutationResult, error) {
			return s.PatchText(ctx, scope, target, TextPatch{OldText: ptr("a"), Content: []byte("b")})
		}},
		{"no match", "NO_MATCH", func() (TextMutationResult, error) {
			return s.PatchText(ctx, scope, target, TextPatch{OldText: ptr("z"), Content: []byte("z")})
		}},
		{"UTF8 cut", "VALIDATION", func() (TextMutationResult, error) { return s.TruncateText(ctx, scope, target, 8, false) }},
		{"zero fill", "NOT_SUPPORTED", func() (TextMutationResult, error) { return s.TruncateText(ctx, scope, target, 12, false) }},
		{"pwrite gap", "NOT_SUPPORTED", func() (TextMutationResult, error) {
			return s.PatchText(ctx, scope, target, TextPatch{Offset: ptr(int64(30)), Content: []byte("x")})
		}},
		{"NUL", "VALIDATION", func() (TextMutationResult, error) { return s.AppendText(ctx, scope, target, []byte{0}) }},
		{"final size", "REQUEST_LIMIT", func() (TextMutationResult, error) {
			return s.AppendText(ctx, scope, target, bytes.Repeat([]byte("x"), 64))
		}},
	} {
		t.Run(tc.name, func(t *testing.T) { _, err := tc.edit(); require.Equal(t, tc.code, reason(err)) })
	}
	stat, err := s.Stat(ctx, scope, target.Locator, true)
	require.NoError(t, err)
	require.Equal(t, created.Stat.Fingerprint, stat.Fingerprint)
	noOp, err := s.WriteText(ctx, scope, target, []byte("a a\r\nchào"))
	require.NoError(t, err)
	require.Equal(t, target.Revision, noOp.Stat.Node.Revision)
	var after int64
	require.NoError(t, db.QueryRow(ctx, `SELECT desired_generation FROM files WHERE node_id=$1`, id).Scan(&after))
	require.Equal(t, generation, after, "no-op and rejected mutations do not change processing")

	// Both writers observe the same revision. Only one append can commit.
	var wg sync.WaitGroup
	start := make(chan struct{})
	errs := make([]error, 2)
	for i := range 2 {
		wg.Go(func() { <-start; _, errs[i] = s.AppendText(ctx, scope, target, []byte("!")) })
	}
	close(start)
	wg.Wait()
	wins := 0
	for _, err := range errs {
		if err == nil {
			wins++
		} else {
			require.Equal(t, "REVISION_MISMATCH", reason(err))
		}
	}
	require.Equal(t, 1, wins)
	read, err := s.ReadText(ctx, scope, target.Locator, TextSelection{Kind: "whole"}, nil)
	require.NoError(t, err)
	require.Equal(t, []byte("a a\r\nchào!"), read.Content)
	_, err = s.AppendText(ctx, scope, target, []byte("!"))
	require.Equal(t, "REVISION_MISMATCH", reason(err), "lost response cannot repeat an append under its old observation")
	_, err = s.WriteText(ctx, scope, target, read.Content)
	require.Equal(t, "REVISION_MISMATCH", reason(err), "equal intended bytes do not excuse stale guards")
	target.Revision = read.Stat.Node.Revision
	target.Fingerprint = &read.Stat.Fingerprint
	patched, err := s.PatchText(ctx, scope, target, TextPatch{OldText: ptr("a"), Content: []byte("b"), ReplaceAll: true})
	require.NoError(t, err)
	require.Equal(t, read.Stat.Fingerprint, patched.BeforeFingerprint)
	require.Equal(t, read.Stat.Node.Revision, patched.BeforeRevision)
	target.Revision = patched.Stat.Node.Revision
	target.Fingerprint = &patched.Stat.Fingerprint
	_, err = s.PatchText(ctx, scope, target, TextPatch{Offset: ptr(int64(0)), Content: []byte("XY")})
	require.NoError(t, err)
	read, err = s.ReadText(ctx, scope, target.Locator, TextSelection{Kind: "whole"}, nil)
	require.NoError(t, err)
	require.Equal(t, []byte("XYb\r\nchào!"), read.Content)
	target.Revision = read.Stat.Node.Revision
	target.Fingerprint = &read.Stat.Fingerprint

	// Quota failures roll back content, size, revision and processing together; shrink at full quota works.
	_, err = db.Exec(ctx, `UPDATE filesystems SET limit_bytes=used_bytes WHERE id=$1`, fs)
	require.NoError(t, err)
	_, err = s.AppendText(ctx, scope, target, []byte("x"))
	require.Equal(t, "QUOTA_EXCEEDED", reason(err))
	stat, err = s.Stat(ctx, scope, target.Locator, true)
	require.NoError(t, err)
	require.Equal(t, read.Stat.Fingerprint, stat.Fingerprint)
	shrunk, err := s.TruncateText(ctx, scope, target, 3, false)
	require.NoError(t, err)
	require.EqualValues(t, 3, shrunk.Stat.ReadableSize)
	var used int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM filesystems WHERE id=$1`, fs).Scan(&used))
	require.EqualValues(t, 3, used)
	_, err = db.Exec(ctx, `UPDATE filesystems SET limit_bytes=1024 WHERE id=$1`, fs)
	require.NoError(t, err)

	// Existing binary data cannot be converted; generated children stay read only.
	blob, err := s.CreateNode(ctx, scope, uuid.New(), CreateNode{Parent: Locator{NodeID: &root}, Name: "source.pdf", File: &InlineFile{Content: []byte("binary"), MediaType: "application/pdf"}})
	require.NoError(t, err)
	_, err = s.WriteText(ctx, scope, TextTarget{Locator: Locator{NodeID: &blob.ID}, Revision: blob.Revision}, []byte("text"))
	require.Equal(t, "NOT_SUPPORTED", reason(err))
	child := uuid.Must(uuid.NewV7())
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'child.txt','file',1)`, child, scope, id)
	require.NoError(t, err)
	p := textPayload([]byte("x"))
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,media_type,text_content,newline_count,text_sha256) VALUES($1,'text','text/plain',$2,$3,$4)`, child, p.Text, p.NewlineCount, p.SHA256)
	require.NoError(t, err)
	_, err = s.WriteText(ctx, scope, TextTarget{Locator: Locator{NodeID: &child}, Revision: 1}, []byte("edit"))
	require.Equal(t, "ARTIFACT_READ_ONLY", reason(err))
	_, err = db.Exec(ctx, `UPDATE filesystems SET used_bytes=used_bytes+1,node_count=node_count+1 WHERE id=$1`, fs)
	require.NoError(t, err)
	changed, err := s.WriteText(ctx, scope, TextTarget{Locator: Locator{NodeID: &id}, Revision: shrunk.Stat.Node.Revision}, []byte("fresh"))
	require.NoError(t, err)
	var parent *uuid.UUID
	require.NoError(t, db.QueryRow(ctx, `SELECT parent_id FROM nodes WHERE id=$1`, child).Scan(&parent))
	require.Nil(t, parent, "mutation detaches stale artifacts")
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM filesystems WHERE id=$1`, fs).Scan(&used))
	require.EqualValues(t, 12, used, "fresh text + binary source + detached artifact remain charged")
	require.Greater(t, changed.Stat.Node.Revision, shrunk.Stat.Node.Revision)
	_, err = s.WriteText(ctx, scope, TextTarget{Locator: Locator{NodeID: &blob.ID, RootID: &root, ExpectedNodeID: &id}, Revision: blob.Revision}, []byte("wrong"))
	require.Equal(t, "TARGET_MISMATCH", reason(err))
	wrong := uuid.Must(uuid.NewV7())
	_, err = s.WriteText(ctx, scope, TextTarget{Locator: Locator{Path: ptr("/notes.bin"), ExpectedNodeID: &wrong}, Revision: changed.Stat.Node.Revision}, []byte("wrong"))
	require.Equal(t, "TARGET_MISMATCH", reason(err))
	_, err = s.WriteText(ctx, scope, TextTarget{Locator: Locator{NodeID: &id}, Revision: changed.Stat.Node.Revision, Fingerprint: ptr("wrong")}, []byte("wrong"))
	require.Equal(t, "CONTENT_CHANGED", reason(err))
	denied := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: uuid.New(), Service: "gateway", Gateway: true})
	_, err = s.WriteText(denied, scope, TextTarget{Locator: Locator{NodeID: &id}, Revision: changed.Stat.Node.Revision}, []byte("wrong"))
	require.Equal(t, "FORBIDDEN", reason(err))
	// Explicit creation has no binary heuristic, and exact bounds/absence semantics are preserved.
	creation.Create.Name = "text.pdf"
	creation.Create.Key = uuid.New()
	full, err := s.WriteText(ctx, scope, creation, bytes.Repeat([]byte("x"), 64))
	require.NoError(t, err)
	var format, status string
	require.NoError(t, db.QueryRow(ctx, `SELECT processing_format,publication_status FROM files WHERE node_id=$1`, full.Stat.Node.ID).Scan(&format, &status))
	require.Equal(t, "text", format)
	require.Equal(t, "parsed", status)
	fullTarget := TextTarget{Locator: Locator{NodeID: &full.Stat.Node.ID}, Revision: full.Stat.Node.Revision}
	_, err = s.AppendText(ctx, scope, fullTarget, []byte("x"))
	require.Equal(t, "REQUEST_LIMIT", reason(err))
	creation.Create.Name = "absent.txt"
	creation.Create.Key = uuid.New()
	_, err = s.TruncateText(ctx, scope, creation, 0, true)
	require.Equal(t, "NOT_FOUND", reason(err))
	_, err = s.TruncateText(ctx, scope, creation, 1, false)
	require.Equal(t, "NOT_SUPPORTED", reason(err))
	_, err = s.PatchText(ctx, scope, creation, TextPatch{Offset: ptr(int64(1)), Content: []byte("x")})
	require.Equal(t, "NOT_SUPPORTED", reason(err))
	_, err = s.ResolveNode(ctx, scope, Locator{Path: ptr("/absent.txt")})
	require.Equal(t, "NOT_FOUND", reason(err))
	zero, err := s.TruncateText(ctx, scope, creation, 0, false)
	require.NoError(t, err)
	require.Zero(t, zero.Stat.ReadableSize)
	creation.Create.Name = "pwrite.txt"
	creation.Create.Key = uuid.New()
	_, err = s.PatchText(ctx, scope, creation, TextPatch{Offset: ptr(int64(0)), Content: []byte("new")})
	require.NoError(t, err)
	_, err = s.WriteText(ctx, scope, creation, []byte("other"))
	require.Equal(t, "IDEMPOTENCY_CONFLICT", reason(err))
	restrictedScope := uuid.Must(uuid.NewV7())
	restricted, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{restrictedScope}, false, true)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", restrictedScope, actor, authz.ScopeWrite)
	_, err = s.WriteText(ctx, restrictedScope, TextTarget{Create: &TextCreation{Key: uuid.New(), Parent: Locator{NodeID: restricted[0].RootID}, Name: "control.txt", MediaType: "text/plain"}}, []byte("no\x01"))
	require.Equal(t, "BLOB_FILES_DISABLED", reason(err))
}
