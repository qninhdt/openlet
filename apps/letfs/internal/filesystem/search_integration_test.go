//go:build integration

package filesystem

import (
	"github.com/qninhdt/openlet/packages/go/apperr"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationBasicSearchLiveOriginalsFiltersAndBoundCursors(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 64}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	bucket, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateBucket(owner, uuid.New(), CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	mounts := []Mount{{Path: "/drive", FilesystemID: fs}}
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeCreate, authz.NodeTrash)
	files := make([]Node, 0, 3)
	for _, name := range []string{"a-report.txt", "b-notes.txt", "c-report.txt"} {
		node, err := s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: name, File: &InlineFile{Content: []byte(name), MediaType: "text/plain"}})
		require.NoError(t, err)
		files = append(files, node)
	}
	_, err = db.Exec(ctx, `UPDATE files SET title='REPORT summary',semantic_type='document:report',context='private context',publication_status='failed' WHERE node_id=$1`, files[1].ID)
	require.NoError(t, err)
	artifact := uuid.New()
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind) VALUES($1,$2,$3,'generated-report.md','file')`, artifact, fs, files[0].ID)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes) VALUES($1,'inline','')`, artifact)
	require.NoError(t, err)
	query := SearchInput{Query: " REPORT ", Limit: ptr(int32(1))}
	_, err = s.SearchFiles(ctx, fs, mounts, query)
	require.Equal(t, apperr.Forbidden, apperr.KindOf(err))
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.Search)
	page, err := s.SearchFiles(ctx, fs, mounts, query)
	require.NoError(t, err)
	require.Len(t, page.Items, 1)
	require.Equal(t, files[0].ID, page.Items[0].Node.ID)
	require.Equal(t, "/drive/a-report.txt", page.Items[0].Path)
	require.NotNil(t, page.NextCursor)
	query.Cursor = page.NextCursor
	page, err = s.SearchFiles(ctx, fs, mounts, query)
	require.NoError(t, err)
	require.Equal(t, files[1].ID, page.Items[0].Node.ID, "title search works despite failed AI processing")
	require.Nil(t, page.Items[0].Node.Context)
	query.Cursor = page.NextCursor
	page, err = s.SearchFiles(ctx, fs, mounts, query)
	require.NoError(t, err)
	require.Equal(t, files[2].ID, page.Items[0].Node.ID)
	require.Nil(t, page.NextCursor)
	query.Cursor = nil
	query.Limit = ptr(int32(100))
	query.Sort, query.Direction = ptr("created_at"), ptr("desc")
	page, err = s.SearchFiles(ctx, fs, mounts, query)
	require.NoError(t, err)
	require.Len(t, page.Items, 3, "generated file is excluded")
	require.Equal(t, files[2].ID, page.Items[0].Node.ID)
	query.Sort, query.Direction = nil, nil
	query.Filters.SemanticType = ptr("document:report")
	page, err = s.SearchFiles(ctx, fs, mounts, query)
	require.NoError(t, err)
	require.Len(t, page.Items, 1)
	require.Equal(t, files[1].ID, page.Items[0].Node.ID)
	query.Filters = SearchFilters{}
	query.Limit = ptr(int32(1))
	first, err := s.SearchFiles(ctx, fs, mounts, query)
	require.NoError(t, err)
	query.Cursor = first.NextCursor
	changed := query
	changed.Query = "different"
	_, err = s.SearchFiles(ctx, fs, mounts, changed)
	require.Equal(t, apperr.Invalid, apperr.KindOf(err))
	_, err = s.SearchFiles(ctx, fs, []Mount{{Path: "/other", FilesystemID: fs}}, query)
	require.Equal(t, apperr.Invalid, apperr.KindOf(err))
	other := uuid.New()
	testfixture.Grant(t, graph, "filesystem", fs, other, authz.Search)
	otherCtx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: other})
	_, err = s.SearchFiles(otherCtx, fs, mounts, query)
	require.Equal(t, apperr.Invalid, apperr.KindOf(err), "cursor binds actor even with identical current permission")
	_, err = s.TrashNode(ctx, fs, mounts, Locator{NodeID: &files[0].ID}, &files[0].Revision)
	require.NoError(t, err)
	query.Cursor, query.Limit = nil, ptr(int32(100))
	page, err = s.SearchFiles(ctx, fs, []Mount{{Path: "/", FilesystemID: fs}}, query)
	require.NoError(t, err)
	require.Len(t, page.Items, 2)
	require.Equal(t, "/b-notes.txt", page.Items[0].Path)
}
