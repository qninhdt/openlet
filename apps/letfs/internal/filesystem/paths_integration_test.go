//go:build integration

package filesystem

import (
	"context"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationLivePathsMetadataAndActionBoundaries(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, server := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100}
	service := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorID: actor, Service: "gateway", Gateway: true})
	bucketID, fsID := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(service, uuid.New(), CreateFilesystem{ID: bucketID, LimitBytes: 1024})
	require.NoError(t, err)
	fs, err := createTestScope(service, &s, uuid.New(), bucketID, fsID)
	require.NoError(t, err)
	root := *fs.RootID

	insert := func(parent uuid.UUID, name, kind string) uuid.UUID {
		t.Helper()
		id := uuid.Must(uuid.NewV7())
		_, err := db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind) VALUES($1,$2,$3,$4,$5)`, id, fsID, parent, name, kind)
		require.NoError(t, err)
		return id
	}
	dir := insert(root, "Việt", "directory")
	file := insert(dir, "report.pdf", "file")
	artifact := insert(file, "report.md", "file")
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,media_type,storage_kind,inline_bytes,context,title) VALUES($1,'application/pdf','inline',''::bytea,'detail context','A report')`, file)
	require.NoError(t, err)
	_, err = s.ResolveNode(ctx, fsID, Locator{Path: ptr("/Việt/report.pdf")})
	require.Equal(t, apperr.Forbidden, apperr.KindOf(err))
	testfixture.Grant(t, graph, "scope", fsID, actor, authz.ScopeReadMetadata, authz.ScopeReadMetadata, authz.ScopeReadMetadata)
	for _, locator := range []Locator{
		{NodeID: &file}, {Path: ptr("/Việt/report.pdf")}, {Path: ptr("report.pdf"), CwdID: &dir},
		{Path: ptr("/@" + file.String())}, {Path: ptr("@" + file.String()), CwdID: &root},
		{Path: ptr("/Việt/../Việt/report.pdf")},
	} {
		node, err := s.ResolveNode(ctx, fsID, locator)
		require.NoError(t, err)
		require.Equal(t, file, node.ID)
		require.Nil(t, node.Context, "metadata response excludes content context")
		require.NoError(t, node.writable())
	}
	node, err := s.ResolveNode(ctx, fsID, Locator{Path: ptr("/@" + artifact.String())})
	require.NoError(t, err)
	require.Equal(t, "ARTIFACT_READ_ONLY", reason(node.writable()))
	for _, locator := range []Locator{{Path: ptr("/..")}, {Path: ptr("@" + file.String()), CwdID: &dir}, {NodeID: ptr(uuid.New())}} {
		_, err = s.ResolveNode(ctx, fsID, locator)
		require.Equal(t, apperr.Missing, apperr.KindOf(err))
	}
	_, err = s.GetNode(ctx, fsID, Locator{NodeID: &file, ExpectedNodeID: ptr(uuid.New())})
	require.Equal(t, "TARGET_MISMATCH", reason(err))
	nodes, err := s.BatchStat(ctx, fsID, []Locator{{NodeID: &file}, {NodeID: &artifact}, {NodeID: &file}})
	require.NoError(t, err)
	require.Equal(t, []uuid.UUID{file, artifact, file}, []uuid.UUID{nodes[0].ID, nodes[1].ID, nodes[2].ID})
	nodes, err = s.BatchStat(ctx, fsID, []Locator{{NodeID: &file}, {NodeID: ptr(uuid.New())}})
	require.Equal(t, apperr.Missing, apperr.KindOf(err))
	require.Nil(t, nodes, "batch failure must not return partial metadata")
	page, err := s.ListNodes(ctx, fsID, Locator{NodeID: &dir}, nil, nil)
	require.NoError(t, err)
	require.Len(t, page.Items, 1)
	require.Nil(t, page.Items[0].Context)
	require.Equal(t, "A report", *page.Items[0].Title)

	second := insert(dir, "second", "directory")
	page, err = s.ListNodes(ctx, fsID, Locator{NodeID: &dir}, nil, ptr(int32(1)))
	require.NoError(t, err)
	require.Equal(t, file, page.Items[0].ID)
	require.NotNil(t, page.NextCursor)
	next, err := s.ListNodes(ctx, fsID, Locator{NodeID: &dir}, page.NextCursor, ptr(int32(1)))
	require.NoError(t, err)
	require.Equal(t, second, next.Items[0].ID)
	require.Nil(t, next.NextCursor)
	_, err = s.ListNodes(ctx, fsID, Locator{NodeID: &root}, page.NextCursor, nil)
	require.Equal(t, apperr.Invalid, apperr.KindOf(err))

	_, err = s.GetFilesystem(ctx, bucketID)
	require.Equal(t, apperr.Forbidden, apperr.KindOf(err), "scope grants confer no filesystem administration")
	testfixture.Grant(t, graph, "filesystem", bucketID, actor, authz.FilesystemRead)
	usage, err := s.GetFilesystem(ctx, bucketID)
	require.NoError(t, err)
	require.EqualValues(t, 1024, usage.LimitBytes)
	_, err = s.GetNode(ctx, uuid.New(), Locator{NodeID: &file})
	require.Equal(t, apperr.Forbidden, apperr.KindOf(err))

	_, err = db.Exec(ctx, `UPDATE nodes SET parent_id=NULL WHERE id=$1`, dir)
	require.NoError(t, err)
	for _, locator := range []Locator{{NodeID: &artifact}, {Path: ptr("/@" + file.String())}, {Path: ptr("report.pdf"), CwdID: &dir}} {
		_, err = s.GetNode(ctx, fsID, locator)
		require.Equal(t, apperr.Missing, apperr.KindOf(err), "detached descendants stay hidden even by raw ID")
	}
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	_, err = s.GetFilesystem(canceled, fsID)
	require.ErrorIs(t, err, context.Canceled)
	require.NoError(t, server.Stop(t.Context(), nil))
	_, err = s.GetFilesystem(ctx, fsID)
	require.Equal(t, apperr.Unavailable, apperr.KindOf(err), "graph outage never reuses previous allow")
}
