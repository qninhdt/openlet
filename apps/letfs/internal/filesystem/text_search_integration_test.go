//go:build integration

package filesystem

import (
	"context"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationTextSearchCandidatesAndLines(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, MaxCopyNodes: 100, MaxOutstanding: 100, MaxCleanupBacklog: 100, InlineLimit: 65536, MaxFileBytes: 65536, ProcessingMaxOutputs: 10, ProcessingMaxOutputBytes: 1000}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: actor, Service: "gateway", Gateway: true})
	fs, scope := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 1 << 20})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{scope}, true, false)
	require.NoError(t, err)
	root := *scopes[0].RootID
	testfixture.Grant(t, graph, "scope", scope, actor, authz.ScopeWrite)
	box, err := s.CreateDirectories(ctx, scope, Locator{NodeID: &root}, []string{"box"}, false)
	require.NoError(t, err)
	create := func(parent uuid.UUID, name, mime, body string) Node {
		t.Helper()
		n, err := s.CreateNode(ctx, scope, uuid.New(), CreateNode{Parent: Locator{NodeID: &parent}, Name: name, File: &InlineFile{Content: []byte(body), MediaType: mime}})
		require.NoError(t, err)
		return n
	}
	alpha := create(box.ID, "alpha.txt", "text/plain", "first\r\nneedle %_\\ end\r\nlast needle")
	beta := create(box.ID, "beta.txt", "text/plain", "unrelated\n")
	blob := create(box.ID, "report.pdf", "application/pdf", "neverneedle")
	create(root, "outside.txt", "text/plain", "needle secret")
	artifact := uuid.Must(uuid.NewV7())
	payload := textPayload([]byte("artifact needle\n"))
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'nested.md','file',16)`, artifact, scope, blob.ID)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,media_type,text_content,newline_count,text_sha256) VALUES($1,'text','text/markdown',$2,$3,$4)`, artifact, payload.Text, payload.NewlineCount, payload.SHA256)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE filesystems SET used_bytes=used_bytes+16,node_count=node_count+1 WHERE id=$1`, fs)
	require.NoError(t, err)
	input := TextSearchInput{Mode: "files", Locator: Locator{Path: ptr("/"), RootID: &box.ID}, Text: "needle"}
	paths := func(result TextSearchResult) []string {
		got := []string{}
		for _, item := range result.Items {
			got = append(got, item.Path)
		}
		return got
	}
	result, err := s.TextSearch(ctx, scope, input)
	require.NoError(t, err)
	require.True(t, result.Complete)
	require.Equal(t, []string{"alpha.txt", "report.pdf", "report.pdf/nested.md"}, paths(result))
	require.True(t, result.Items[2].Stat.Node.ReadOnly())
	for _, text := range []string{"%_", `\`} {
		input.Text = text
		result, err = s.TextSearch(ctx, scope, input)
		require.NoError(t, err)
		require.Equal(t, []string{"alpha.txt", "report.pdf"}, paths(result), "wildcards are literals; every blob remains a safe metadata candidate")
	}
	input.Text = "NEEDLE"
	input.IgnoreCase = true
	result, err = s.TextSearch(ctx, scope, input)
	require.NoError(t, err)
	require.Len(t, result.Items, 4, "Unicode-insensitive narrowing must not omit possible Mirage matches")
	input.IgnoreCase = false
	input.Text = "absent"
	result, err = s.TextSearch(ctx, scope, input)
	require.NoError(t, err)
	require.Equal(t, []string{"report.pdf"}, paths(result))
	input.Text = "\x00"
	result, err = s.TextSearch(ctx, scope, input)
	require.NoError(t, err)
	require.True(t, result.Complete)
	require.Empty(t, result.Items)
	input.Text = "needle"
	input.MaxFiles = ptr(int32(1))
	result, err = s.TextSearch(ctx, scope, input)
	require.NoError(t, err)
	require.False(t, result.Complete)
	require.Empty(t, result.Items)
	input.MaxFiles = nil
	input.MaxBytes = ptr(int32(3))
	result, err = s.TextSearch(ctx, scope, input)
	require.NoError(t, err)
	require.False(t, result.Complete)
	require.Empty(t, result.Items)
	lines := TextSearchInput{Mode: "lines", Text: "needle", Locator: Locator{NodeID: &alpha.ID, RootID: &box.ID}}
	result, err = s.TextSearch(ctx, scope, lines)
	require.NoError(t, err)
	require.True(t, result.Complete)
	require.Equal(t, []byte("needle %_\\ end\r\nlast needle"), result.Content)
	stat, err := s.Stat(ctx, scope, lines.Locator, true)
	require.NoError(t, err)
	require.Equal(t, stat.Fingerprint, result.Stat.Fingerprint)
	lines.MaxLines = ptr(int32(1))
	result, err = s.TextSearch(ctx, scope, lines)
	require.NoError(t, err)
	require.False(t, result.Complete)
	require.Empty(t, result.Content)
	require.Nil(t, result.Stat)
	lines.MaxLines = nil
	lines.Locator.NodeID = &blob.ID
	lines.Text = "neverneedle"
	result, err = s.TextSearch(ctx, scope, lines)
	require.NoError(t, err)
	require.Empty(t, result.Content, "raw blob bytes are never searched")
	lines.Text = "nested.md"
	result, err = s.TextSearch(ctx, scope, lines)
	require.NoError(t, err)
	require.Contains(t, string(result.Content), "nested.md")
	require.NotContains(t, string(result.Content), "neverneedle")
	// Current writes are immediately visible; detached processing artifacts are never candidates.
	_, err = s.AppendText(ctx, scope, TextTarget{Locator: Locator{NodeID: &beta.ID}, Revision: beta.Revision}, []byte("new-term"))
	require.NoError(t, err)
	input.MaxBytes = nil
	input.Text = "new-term"
	result, err = s.TextSearch(ctx, scope, input)
	require.NoError(t, err)
	require.Equal(t, []string{"beta.txt", "report.pdf"}, paths(result))
	_, err = s.ReplaceContent(ctx, scope, Locator{NodeID: &blob.ID}, &blob.Revision, []byte("replacement"), "application/pdf")
	require.NoError(t, err)
	input.Text = "artifact"
	result, err = s.TextSearch(ctx, scope, input)
	require.NoError(t, err)
	require.Equal(t, []string{"report.pdf"}, paths(result))
	current := Generation{FileID: blob.ID, Generation: 2}
	_, err = s.PrepareParse(t.Context(), current)
	require.NoError(t, err)
	body := []byte("publishedneedle\n")
	size := int64(len(body))
	upload, err := s.PrepareParseOutput(t.Context(), current, ProcessingOutput{Path: "published.md", Storage: "inline", SizeBytes: &size})
	require.NoError(t, err)
	output := OutputScope{Source: current, Stage: "parse", UploadID: upload.ID}
	_, err = s.WriteOutputBytes(t.Context(), output, body)
	require.NoError(t, err)
	_, err = s.CompleteOutputUpload(t.Context(), output, nil)
	require.NoError(t, err)
	input.Text = "publishedneedle"
	result, err = s.TextSearch(ctx, scope, input)
	require.NoError(t, err)
	require.Equal(t, []string{"report.pdf"}, paths(result), "unpublished output is not live")
	require.NoError(t, s.CompleteParse(t.Context(), current, ParseManifest{Uploads: []uuid.UUID{upload.ID}}))
	result, err = s.TextSearch(ctx, scope, input)
	require.NoError(t, err)
	require.Equal(t, []string{"report.pdf", "report.pdf/published.md"}, paths(result))
	_, err = s.TextSearch(ctx, scope, TextSearchInput{Mode: "lines", Text: "secret", Locator: Locator{NodeID: &root, RootID: &box.ID}})
	require.Equal(t, "NOT_FOUND", reason(err))
	denied := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: uuid.New(), Service: "gateway", Gateway: true})
	_, err = s.TextSearch(denied, scope, input)
	require.Equal(t, "FORBIDDEN", reason(err))
	// The same indexed query observes the existing native lifecycle without an index job.
	life, err := s.WriteText(ctx, scope, TextTarget{Create: &TextCreation{Key: uuid.New(), Parent: Locator{NodeID: &box.ID}, Name: "life.txt", MediaType: "text/plain"}}, []byte("lifecycle-needle"))
	require.NoError(t, err)
	assertTextPaths := func(text string, want []string) {
		t.Helper()
		query := TextSearchInput{Mode: "files", Locator: Locator{NodeID: &box.ID}, Text: text}
		found, err := s.TextSearch(ctx, scope, query)
		require.NoError(t, err)
		require.True(t, found.Complete)
		actual := []string{}
		for _, item := range found.Items {
			if item.Stat.StorageKind == "text" {
				actual = append(actual, item.Path)
			}
		}
		require.Equal(t, want, actual)
	}
	assertTextPaths("lifecycle-needle", []string{"life.txt"})
	copy, err := s.CopyNode(ctx, scope, uuid.New(), CreateCopy{SourceID: life.Stat.Node.ID, ParentID: box.ID, Name: "life-copy.txt", Revision: &life.Stat.Node.Revision})
	require.NoError(t, err)
	assertTextPaths("lifecycle-needle", []string{"life-copy.txt", "life.txt"})
	entry, err := s.TrashNode(ctx, scope, Locator{NodeID: &copy.ID}, &copy.Revision, false)
	require.NoError(t, err)
	assertTextPaths("lifecycle-needle", []string{"life.txt"})
	copy, err = s.RestoreTrash(ctx, scope, entry.ID, RestoreTrash{})
	require.NoError(t, err)
	assertTextPaths("lifecycle-needle", []string{"life-copy.txt", "life.txt"})
	_, err = s.UpdateNode(ctx, scope, UpdateNode{Locator: Locator{NodeID: &copy.ID}, Revision: &copy.Revision, Parent: &Locator{NodeID: &root}})
	require.NoError(t, err)
	assertTextPaths("lifecycle-needle", []string{"life.txt"})
	tx, err := db.Begin(ctx)
	require.NoError(t, err)
	pending := textPayload([]byte("uncommitted"))
	_, err = tx.Exec(ctx, `UPDATE files SET text_content=$2,newline_count=$3,text_sha256=$4 WHERE node_id=$1`, life.Stat.Node.ID, pending.Text, pending.NewlineCount, pending.SHA256)
	require.NoError(t, err)
	assertTextPaths("uncommitted", []string{})
	require.NoError(t, tx.Rollback(ctx))
	assertTextPaths("lifecycle-needle", []string{"life.txt"})
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	_, err = s.TextSearch(canceled, scope, input)
	require.Error(t, err)
	_, err = graph.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "scope", OptionalResourceId: scope.String()}})
	require.NoError(t, err)
	_, err = s.TextSearch(ctx, scope, input)
	require.Equal(t, "FORBIDDEN", reason(err), "previously returned candidates do not grant future access")
}
