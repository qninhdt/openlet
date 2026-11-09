//go:build integration

package filesystem

import (
	"archive/zip"
	"bytes"
	"io"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"golang.org/x/sync/semaphore"
)

func TestIntegrationInlineTextExactBytesAcrossConsumers(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, MaxCopyNodes: 100, InlineLimit: 64, MaxFileBytes: 64,
		MaxOutstanding: 10, MaxCleanupBacklog: 10,
		Archive:      ArchiveConfig{MaxEntries: 100, MaxSourceBytes: 4096, MaxOutputBytes: 16384, Runtime: 5 * time.Second},
		ArchiveSlots: semaphore.NewWeighted(1)}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: actor, Service: "gateway", Gateway: true})
	fsID, scopeID := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fsID, LimitBytes: 4096})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(owner, uuid.New(), fsID, []uuid.UUID{scopeID}, true, true)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", scopeID, actor, authz.ScopeWrite)
	dir, err := s.CreateNode(ctx, scopeID, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "files"})
	require.NoError(t, err)
	create := func(name, mime string, content []byte) Node {
		t.Helper()
		node, err := s.CreateNode(ctx, scopeID, uuid.New(), CreateNode{Parent: Locator{NodeID: &dir.ID}, Name: name, File: &InlineFile{Content: content, MediaType: mime}})
		require.NoError(t, err)
		return node
	}
	content := []byte("\xef\xbb\xbfXin chào 🌏\r\nlast  ")
	file := create("notes.txt", "text/plain", content)
	var kind, text, hash string
	var lf, size int64
	var inline []byte
	require.NoError(t, db.QueryRow(ctx, `SELECT f.storage_kind,f.text_content,f.inline_bytes,f.newline_count,f.text_sha256,n.size_bytes FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.id=$1`, file.ID).Scan(&kind, &text, &inline, &lf, &hash, &size))
	require.Equal(t, "text", kind)
	require.Equal(t, string(content), text)
	require.Nil(t, inline)
	require.EqualValues(t, 1, lf)
	require.Len(t, hash, 64)
	require.EqualValues(t, len(content), size)
	_, err = db.Exec(ctx, `UPDATE files SET newline_count=0 WHERE node_id=$1`, file.ID)
	require.Error(t, err, "database rejects inconsistent text metrics")
	_, err = db.Exec(ctx, `UPDATE files SET text_sha256=repeat('0',64) WHERE node_id=$1`, file.ID)
	require.Error(t, err, "database rejects inconsistent content hash")
	checkDownload := func(node Node, expected []byte) {
		t.Helper()
		download, err := s.GetDownload(ctx, scopeID, node.ID, &node.Revision)
		require.NoError(t, err)
		require.Equal(t, expected, download.InlineContent)
		require.Empty(t, download.SignedURL)
		require.EqualValues(t, len(expected), download.SizeBytes)
	}
	checkDownload(file, content)
	empty := create("empty.txt", "text/plain", nil)
	checkDownload(empty, []byte{})
	full := create("limit.txt", "text/plain", bytes.Repeat([]byte("x"), 64))
	checkDownload(full, bytes.Repeat([]byte("x"), 64))
	_, err = s.CreateNode(ctx, scopeID, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "over.txt", File: &InlineFile{Content: bytes.Repeat([]byte("x"), 65), MediaType: "text/plain"}})
	require.Equal(t, "REQUEST_LIMIT", reason(err))
	for i, data := range [][]byte{{0xff, 0, 1}, []byte("before\x00after")} {
		name := []string{"invalid.txt", "nul-byte.txt"}[i]
		node := create(name, "text/plain", data)
		checkDownload(node, data)
		require.NoError(t, db.QueryRow(ctx, `SELECT storage_kind FROM files WHERE node_id=$1`, node.ID).Scan(&kind))
		require.Equal(t, "inline", kind)
	}
	copied, err := s.CopyNode(ctx, scopeID, uuid.New(), CreateCopy{SourceID: file.ID, ParentID: *scopes[0].RootID, Name: "copy.txt", Revision: &file.Revision})
	require.NoError(t, err)
	checkDownload(copied, content)
	require.NoError(t, db.QueryRow(ctx, `SELECT storage_kind,newline_count,text_sha256 FROM files WHERE node_id=$1`, copied.ID).Scan(&kind, &lf, &text))
	require.Equal(t, "text", kind)
	require.Equal(t, hash, text)
	require.EqualValues(t, 1, lf)
	prepared, err := s.PrepareEnrichment(t.Context(), Generation{FileID: file.ID, Generation: 1})
	require.NoError(t, err)
	require.Len(t, prepared.Nodes, 1)
	require.Equal(t, content, prepared.Nodes[0].Content.InlineContent)
	stream, err := s.OpenArchive(ctx, scopeID, dir.ID)
	require.NoError(t, err)
	archive, err := io.ReadAll(stream)
	require.NoError(t, err)
	require.NoError(t, stream.Close())
	reader, err := zip.NewReader(bytes.NewReader(archive), int64(len(archive)))
	require.NoError(t, err)
	var found bool
	for _, entry := range reader.File {
		if entry.Name == "notes.txt" {
			body, err := entry.Open()
			require.NoError(t, err)
			data, err := io.ReadAll(body)
			require.NoError(t, err)
			require.NoError(t, body.Close())
			require.Equal(t, content, data)
			found = true
		}
	}
	require.True(t, found)
	// Lowering a write limit never makes existing stored text unreadable.
	s.InlineLimit = 1
	checkDownload(file, content)
	s.InlineLimit = 64
	file, err = s.ReplaceContent(ctx, scopeID, Locator{NodeID: &file.ID}, &file.Revision, []byte{0xff, 0}, "application/octet-stream")
	require.NoError(t, err)
	checkDownload(file, []byte{0xff, 0})
	require.NoError(t, db.QueryRow(ctx, `SELECT storage_kind,text_content IS NULL AND newline_count IS NULL AND text_sha256 IS NULL FROM files WHERE node_id=$1`, file.ID).Scan(&kind, &found))
	require.Equal(t, "inline", kind)
	require.True(t, found)
}
