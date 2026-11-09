//go:build integration

package filesystem

import (
	"bytes"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationScopeBlobRestrictions(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, MaxCopyNodes: 10, InlineLimit: 128, MaxFileBytes: 128,
		MaxOutstanding: 10, MaxCleanupBacklog: 10, ProcessingMaxOutputs: 10, ProcessingMaxOutputBytes: 1024}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, Service: "gateway", Gateway: true, ActorID: actor})
	filesystemID, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	input := CreateFilesystem{ID: filesystemID, LimitBytes: 4096}
	key := uuid.New()
	createdFS, err := s.CreateFilesystem(owner, key, input)
	require.NoError(t, err)
	replayed, err := s.CreateFilesystem(owner, key, input)
	require.NoError(t, err)
	require.Equal(t, createdFS, replayed)
	key = uuid.New()
	scopes, err := s.CreateScopes(owner, key, filesystemID, []uuid.UUID{fs}, false, true)
	require.NoError(t, err)
	created := scopes[0]
	require.False(t, created.AllowBlobFiles)
	require.True(t, created.AllowIndexing)
	repeated, err := s.CreateScopes(owner, key, filesystemID, []uuid.UUID{fs}, false, true)
	require.NoError(t, err)
	require.Equal(t, scopes, repeated)
	for _, options := range [][2]bool{{true, true}, {false, false}} {
		for _, requestKey := range []uuid.UUID{key, uuid.New()} {
			_, err = s.CreateScopes(owner, requestKey, filesystemID, []uuid.UUID{fs}, options[0], options[1])
			require.Equal(t, "SCOPE_CONFLICT", reason(err))
		}
	}
	testfixture.Grant(t, graph, "scope", fs, actor, authz.ScopeWrite)
	unrestricted, err := createTestScope(owner, &s, uuid.New(), filesystemID, uuid.Must(uuid.NewV7()))
	require.NoError(t, err)
	require.True(t, unrestricted.AllowBlobFiles)
	require.True(t, unrestricted.AllowIndexing)
	testfixture.Grant(t, graph, "scope", unrestricted.ID, actor, authz.ScopeWrite)
	binary, err := s.CreateNode(ctx, unrestricted.ID, uuid.New(), CreateNode{Parent: Locator{NodeID: unrestricted.RootID}, Name: "bytes.bin", File: &InlineFile{Content: []byte{0, 255}, MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	copyInput, err := s.prepareCopy(ctx, unrestricted.ID, uuid.New(), CreateCopy{DestinationScopeID: fs, SourceID: binary.ID, ParentID: *created.RootID, Name: "binary-copy-checked", Revision: &binary.Revision})
	require.NoError(t, err)
	require.Equal(t, "BLOB_FILES_DISABLED", reason(s.copyTreeData(ctx, copyInput)))
	_, err = db.Exec(ctx, `UPDATE files SET storage_kind='object',inline_bytes=NULL,text_content=NULL,newline_count=NULL,text_sha256=NULL,object_key='objects/source' WHERE node_id=$1`, binary.ID)
	require.NoError(t, err)
	_, err = s.prepareCopy(ctx, unrestricted.ID, uuid.New(), CreateCopy{DestinationScopeID: fs, SourceID: binary.ID, ParentID: *created.RootID, Name: "blob-copy", Revision: &binary.Revision})
	require.Equal(t, "BLOB_FILES_DISABLED", reason(err), "reject before touching object storage")
	root := Locator{NodeID: created.RootID}
	create := func(name string, content []byte) (Node, error) {
		return s.CreateNode(ctx, fs, uuid.New(), CreateNode{Parent: root, Name: name, File: &InlineFile{Content: content, MediaType: "application/octet-stream"}})
	}
	dir, err := s.CreateNode(ctx, fs, uuid.New(), CreateNode{Parent: root, Name: "notes"})
	require.NoError(t, err)
	require.Equal(t, "directory", dir.Kind)
	for _, test := range []struct {
		name    string
		content []byte
	}{
		{"empty", nil}, {"config.json", []byte(`{"enabled":true}`)}, {"main.go", []byte("package main\n")},
	} {
		_, err = create(test.name, test.content)
		require.NoError(t, err)
	}
	text := []byte("Xin chào 🌏\r\n\t# Notes\n")
	file, err := create("notes.pdf", text)
	require.NoError(t, err)
	var used, count int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM filesystems WHERE id=$1`, filesystemID).Scan(&used))
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, filesystemID).Scan(&count))
	for _, content := range [][]byte{{0xff}, {0}, []byte("text\x01")} {
		_, err = create("binary", content)
		require.Equal(t, "BLOB_FILES_DISABLED", reason(err))
		_, err = s.ReplaceContent(ctx, fs, Locator{NodeID: &file.ID}, &file.Revision, content, "text/plain")
		require.Equal(t, "BLOB_FILES_DISABLED", reason(err))
	}
	_, err = create("large.txt", bytes.Repeat([]byte("a"), 129))
	require.Equal(t, "REQUEST_LIMIT", reason(err))
	var saved []byte
	var kind, format, publication string
	var afterUsed, afterCount, revision int64
	require.NoError(t, db.QueryRow(ctx, `SELECT COALESCE(f.inline_bytes,convert_to(f.text_content,'UTF8')),f.storage_kind,f.processing_format,f.publication_status,n.revision FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.id=$1`, file.ID).Scan(&saved, &kind, &format, &publication, &revision))
	require.Equal(t, text, saved)
	require.Equal(t, "text", kind)
	require.Equal(t, "text", format, "filename cannot route text to a binary parser")
	require.Equal(t, "parsed", publication)
	require.Equal(t, file.Revision, revision)
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM filesystems WHERE id=$1`, filesystemID).Scan(&afterUsed))
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, filesystemID).Scan(&afterCount))
	require.Equal(t, used, afterUsed)
	require.Equal(t, count, afterCount)
	for _, target := range []UploadCreation{
		{Destination: &UploadDestination{Parent: root, Name: "upload.txt"}, SizeBytes: ptr(int64(1)), MediaType: "text/plain"},
		{Replacement: &UploadReplacement{Locator: Locator{NodeID: &file.ID}, Revision: &file.Revision}, SizeBytes: ptr(int64(1)), MediaType: "text/plain"},
	} {
		_, err = s.CreateUpload(ctx, fs, uuid.New(), target)
		require.Equal(t, "BLOB_FILES_DISABLED", reason(err))
	}
	file, err = s.ReplaceContent(ctx, fs, Locator{NodeID: &file.ID}, &file.Revision, []byte("updated\n"), "text/plain")
	require.NoError(t, err)
	admission, err := s.prepareCopy(ctx, fs, uuid.New(), CreateCopy{DestinationScopeID: fs, SourceID: file.ID, ParentID: *created.RootID, Name: "copy", Revision: &file.Revision})
	require.NoError(t, err)
	require.NoError(t, s.copyTreeData(ctx, admission))
	require.NoError(t, db.QueryRow(ctx, `SELECT COALESCE(inline_bytes,convert_to(text_content,'UTF8')),storage_kind FROM files WHERE node_id=$1`, admission.Root.Destination).Scan(&saved, &kind))
	require.Equal(t, []byte("updated\n"), saved)
	require.Equal(t, "text", kind)

	source := Generation{FileID: file.ID, Generation: 2}
	parsed, err := s.PrepareParse(ctx, source)
	require.NoError(t, err)
	require.True(t, parsed.Complete)
	output := ProcessingOutput{Path: "README.md", Storage: "object", SizeBytes: ptr(int64(3))}
	_, err = s.PrepareEnrichmentOutput(ctx, source, output)
	require.Equal(t, "BLOB_FILES_DISABLED", reason(err))
	output.Storage = "inline"
	upload, err := s.PrepareEnrichmentOutput(ctx, source, output)
	require.NoError(t, err)
	scope := OutputScope{Source: source, Stage: "enrichment", UploadID: upload.ID}
	_, err = s.WriteOutputBytes(ctx, scope, []byte{0, 1, 2})
	require.Equal(t, "BLOB_FILES_DISABLED", reason(err))
	_, err = s.WriteOutputBytes(ctx, scope, []byte("ok\n"))
	require.NoError(t, err)
	_, err = s.CompleteOutputUpload(ctx, scope, nil)
	require.NoError(t, err)
	_, err = s.Reprocess(ctx, fs, admission.Root.Destination, uuid.New())
	require.NoError(t, err)
}

func TestIntegrationScopeIndexingDisabledPreservesEnrichment(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 100, MaxFileBytes: 100, ProcessingMaxOutputs: 10}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, Service: "gateway", Gateway: true, ActorID: actor})
	fs := uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 1000})
	require.NoError(t, err)
	for _, index := range []bool{false, true} {
		scopes, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{uuid.Must(uuid.NewV7())}, true, index)
		require.NoError(t, err)
		scope := scopes[0]
		testfixture.Grant(t, graph, "scope", scope.ID, actor, authz.ScopeWrite)
		file, err := s.CreateNode(ctx, scope.ID, uuid.New(), CreateNode{Parent: Locator{NodeID: scope.RootID}, Name: "notes.txt", File: &InlineFile{Content: []byte("notes"), MediaType: "text/plain"}})
		require.NoError(t, err)
		reprocessed, err := s.Reprocess(ctx, scope.ID, file.ID, uuid.New())
		require.NoError(t, err)
		source := Generation{FileID: file.ID, Generation: reprocessed.Generation}
		dispatch, err := s.PendingProcessing(ctx, file.ID)
		require.NoError(t, err)
		require.Equal(t, index, dispatch.AllowIndexing)
		parsed, err := s.PrepareParse(ctx, source)
		require.NoError(t, err)
		require.True(t, parsed.Complete)
		enriched, err := s.PrepareEnrichment(ctx, source)
		require.NoError(t, err)
		require.Len(t, enriched.Nodes, 1)
		manifest := EnrichmentManifest{Nodes: []EnrichmentUpdate{{ID: file.ID, Metadata: &SemanticMetadata{Title: "Notes", Description: "Notes", SemanticType: "text:notes", Context: "Notes"}}}}
		require.NoError(t, s.CompleteEnrichment(ctx, source, manifest))
		pending, err := s.ProcessingCandidates(ctx)
		require.NoError(t, err)
		found := false
		for _, candidate := range pending {
			if candidate.Source == source {
				found = true
			}
		}
		require.Equal(t, index, found, "completed non-indexed files must not be redispatched")
		missing, err := s.BackfillCandidates(ctx, "missing", uuid.Nil, 100)
		require.NoError(t, err)
		found = false
		for _, candidate := range missing {
			if candidate.Dispatch.Source == source {
				found = true
			}
		}
		require.Equal(t, index, found)
		if !index {
			_, err = s.PrepareIndex(ctx, source)
			require.Equal(t, "INDEXING_DISABLED", reason(err), "scope fence precedes vector-provider configuration")
			require.Equal(t, "INDEXING_DISABLED", reason(s.CompleteIndex(ctx, source)))
			require.Equal(t, "INDEXING_DISABLED", reason(s.FailIndex(ctx, source, "PROCESSING_FAILED")))
			var completed bool
			require.NoError(t, db.QueryRow(ctx, `SELECT expires_at IS NOT NULL FROM idempotency_keys WHERE operation='process-file' AND result->>'file_id'=$1`, file.ID.String()).Scan(&completed))
			require.True(t, completed)
			page, err := s.SemanticSearch(ctx, scope.ID, SemanticSearchInput{Query: "notes"})
			require.NoError(t, err, "disabled indexing requires no search or embedding provider")
			require.Empty(t, page.Items)
		}
	}
}
