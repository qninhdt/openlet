//go:build integration

package filesystem

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationNativeTextReadsMetadataAndTree(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 1048576, MaxFileBytes: 104857600}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: actor, Service: "gateway", Gateway: true})
	fs, scope := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 1 << 24})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{scope}, true, true)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", scope, actor, authz.ScopeWrite)
	body := []byte("\xef\xbb\xbfchào\r\n\nlast  ")
	file, err := s.CreateNode(ctx, scope, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "notes.txt", File: &InlineFile{Content: body, MediaType: "text/plain"}})
	require.NoError(t, err)
	loc := Locator{Path: ptr("/notes.txt"), RootID: scopes[0].RootID}
	stat, err := s.Stat(ctx, scope, loc, true)
	require.NoError(t, err)
	require.Equal(t, "text", stat.RepresentationKind)
	require.EqualValues(t, len(body), stat.ReadableSize)
	require.EqualValues(t, 2, *stat.NewlineCount)
	sha := sha256.Sum256(body)
	require.Equal(t, hex.EncodeToString(sha[:]), *stat.SHA256)
	read, err := s.ReadText(ctx, scope, loc, TextSelection{Kind: "tail", LineCount: 2}, &stat.Fingerprint)
	require.NoError(t, err)
	require.Equal(t, []byte("\nlast  "), read.Content)
	require.EqualValues(t, 10, read.Offset)
	require.Equal(t, stat.Fingerprint, read.Stat.Fingerprint)
	metric, err := s.TextMetrics(ctx, scope, loc, "sha256")
	require.NoError(t, err)
	require.True(t, metric.Supported)
	require.Equal(t, *stat.SHA256, metric.Digest)
	metric, err = s.TextMetrics(ctx, scope, loc, "unknown")
	require.NoError(t, err)
	require.False(t, metric.Supported)
	require.Empty(t, metric.Digest)
	_, err = s.ReplaceContent(ctx, scope, Locator{NodeID: &file.ID}, &file.Revision, []byte("updated"), "text/plain")
	require.NoError(t, err)
	_, err = s.ReadText(ctx, scope, loc, TextSelection{Kind: "whole"}, &stat.Fingerprint)
	require.Equal(t, "CONTENT_CHANGED", reason(err))
	_, err = s.ReadText(ctx, scope, Locator{NodeID: scopes[0].RootID}, TextSelection{Kind: "whole"}, nil)
	require.Equal(t, "NOT_FILE", reason(err))
	denied := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: uuid.New(), Service: "gateway", Gateway: true})
	_, err = s.Stat(denied, scope, loc, true)
	require.Equal(t, "FORBIDDEN", reason(err))
	_, err = s.ReadText(denied, scope, loc, TextSelection{Kind: "whole"}, nil)
	require.Equal(t, "FORBIDDEN", reason(err))
	_, err = s.ReadTree(denied, scope, Locator{Path: ptr("/")}, TreeOptions{})
	require.Equal(t, "FORBIDDEN", reason(err))
	// A large object-backed text source is represented without opening storage.
	blob, dir, child := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'report.txt','file',99999999),($4,$2,$1,'nested','directory',0),($5,$2,$4,'report.md','file',6)`, blob, scope, scopes[0].RootID, dir, child)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,object_key,media_type,desired_generation,processing_format,publication_status) VALUES($1,'object','SECRET-KEY-NEVER-EXPOSE','text/plain',1,'text','parsed');`, blob)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes,media_type) VALUES($1,'inline','detail','text/markdown')`, child)
	require.NoError(t, err)
	blobLoc := Locator{Path: ptr("/@" + blob.String()), RootID: scopes[0].RootID}
	blobRead, err := s.ReadText(ctx, scope, blobLoc, TextSelection{Kind: "whole"}, nil)
	require.NoError(t, err)
	require.Equal(t, "blob_metadata", blobRead.Stat.RepresentationKind)
	require.EqualValues(t, 99999999, blobRead.Stat.Node.SizeBytes)
	require.NotContains(t, string(blobRead.Content), "SECRET-KEY")
	require.NotContains(t, string(blobRead.Content), "detail")
	require.EqualValues(t, len(blobRead.Content), blobRead.Stat.ReadableSize)
	var metadata struct {
		Artifacts []artifactMetadata `json:"artifacts"`
	}
	require.NoError(t, json.Unmarshal(blobRead.Content, &metadata))
	require.Len(t, metadata.Artifacts, 1)
	require.Equal(t, "nested", metadata.Artifacts[0].Path)
	require.Len(t, metadata.Artifacts[0].Children, 1)
	require.Equal(t, "nested/report.md", metadata.Artifacts[0].Children[0].Path)
	byName, err := s.Stat(ctx, scope, Locator{Path: ptr("/report.txt/nested/report.md")}, false)
	require.NoError(t, err)
	require.Equal(t, child, byName.Node.ID)
	require.True(t, byName.Node.ReadOnly())
	_, err = db.Exec(ctx, `UPDATE files SET publication_status='enriched' WHERE node_id=$1`, blob)
	require.NoError(t, err)
	_, err = s.ReadText(ctx, scope, blobLoc, TextSelection{Kind: "whole"}, &blobRead.Stat.Fingerprint)
	require.Equal(t, "CONTENT_CHANGED", reason(err), "processing changes invalidate metadata even without node revision change")
	root := Locator{Path: ptr("/")}
	var paths []string
	var cursor *string
	for range 10 {
		page, err := s.ReadTree(ctx, scope, root, TreeOptions{Limit: ptr(int32(1)), Cursor: cursor})
		require.NoError(t, err)
		for _, item := range page.Items {
			paths = append(paths, item.Path)
		}
		if page.Complete {
			require.Nil(t, page.NextCursor)
			break
		}
		require.NotNil(t, page.NextCursor)
		cursor = page.NextCursor
	}
	require.Equal(t, []string{"notes.txt", "report.txt", "report.txt/nested", "report.txt/nested/report.md"}, paths)
	page, err := s.ReadTree(ctx, scope, root, TreeOptions{Limit: ptr(int32(1))})
	require.NoError(t, err)
	require.NotNil(t, page.NextCursor)
	_, err = s.ReadTree(ctx, scope, root, TreeOptions{Depth: ptr(int32(1)), Cursor: page.NextCursor})
	require.Equal(t, "VALIDATION", reason(err), "cursor binds depth")
	_, err = s.ReadTree(ctx, scope, Locator{NodeID: &dir}, TreeOptions{Cursor: page.NextCursor})
	require.Equal(t, "VALIDATION", reason(err), "cursor binds traversal root")
	page, err = s.ReadTree(ctx, scope, root, TreeOptions{Depth: ptr(int32(1))})
	require.NoError(t, err)
	require.Len(t, page.Items, 2)
	require.True(t, page.Complete)
	_, err = s.ReadTree(ctx, scope, root, TreeOptions{MaxBytes: ptr(int32(1))})
	require.Equal(t, "RESOURCE_LIMIT", reason(err))
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	_, err = s.ReadText(canceled, scope, loc, TextSelection{Kind: "whole"}, nil)
	require.ErrorIs(t, err, context.Canceled)
	// Cursor bindings cannot be reused by another authorized subject.
	other := uuid.New()
	testfixture.Grant(t, graph, "scope", scope, other, authz.ScopeReadMetadata)
	otherCtx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: other, Service: "gateway", Gateway: true})
	_, err = s.ReadTree(otherCtx, scope, root, TreeOptions{Cursor: cursor})
	require.Equal(t, "VALIDATION", reason(err))
	// A source with metadata above the representation cap remains navigable in bounded pages.
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind)
 SELECT uuidv7(),$1,$2,'artifact-'||lpad(i::text,5,'0'),'directory' FROM generate_series(1,10001) i`, scope, blob)
	require.NoError(t, err)
	_, err = s.ReadText(ctx, scope, blobLoc, TextSelection{Kind: "whole"}, nil)
	require.Equal(t, "RESOURCE_LIMIT", reason(err))
	page, err = s.ReadTree(ctx, scope, blobLoc, TreeOptions{Limit: ptr(int32(1))})
	require.NoError(t, err)
	require.False(t, page.Complete)
	require.Len(t, page.Items, 1)
	require.Equal(t, "artifact-00001", page.Items[0].Path)
	require.True(t, page.Items[0].Stat.Node.ReadOnly())
}
