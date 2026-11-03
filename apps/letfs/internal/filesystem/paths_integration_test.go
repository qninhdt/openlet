//go:build integration

package filesystem

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestIntegrationLivePathsMetadataAndActionBoundaries(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, server := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100}
	service := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorID: actor, Service: "gateway", Gateway: true})
	bucketID, fsID := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateBucket(service, uuid.New(), CreateBucket{ID: bucketID, LimitBytes: 1024})
	require.NoError(t, err)
	fs, err := s.CreateFilesystem(service, uuid.New(), CreateFilesystem{ID: fsID, BucketID: bucketID, RootName: "files"})
	require.NoError(t, err)
	root := *fs.RootID
	mounts := []Mount{{Path: "/drive", FilesystemID: fsID}}
	insert := func(parent uuid.UUID, name, kind string) uuid.UUID {
		t.Helper()
		id := uuid.Must(uuid.NewV7())
		_, err := db.Exec(ctx, `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind) VALUES($1,$2,$3,$4,$5)`, id, fsID, parent, name, kind)
		require.NoError(t, err)
		return id
	}
	dir := insert(root, "Việt", "directory")
	file := insert(dir, "report.pdf", "file")
	artifact := insert(file, "report.md", "file")
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,media_type,storage_kind,inline_bytes,context,title) VALUES($1,'application/pdf','inline',''::bytea,'detail context','A report')`, file)
	require.NoError(t, err)
	_, err = s.ResolveNode(ctx, fsID, mounts, Locator{Path: ptr("/drive/Việt/report.pdf")})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	testfixture.Grant(t, graph, "filesystem", fsID, actor, authz.NodeRead, authz.NodeResolve, authz.NodeList)
	for _, locator := range []Locator{
		{NodeID: &file}, {Path: ptr("/drive/Việt/report.pdf")}, {Path: ptr("report.pdf"), CwdID: &dir},
		{Path: ptr("/drive/@" + file.String())}, {Path: ptr("@" + file.String()), CwdID: &root},
		{Path: ptr("/drive/Việt/../Việt/report.pdf")},
	} {
		node, err := s.ResolveNode(ctx, fsID, mounts, locator)
		require.NoError(t, err)
		require.Equal(t, file, node.ID)
		require.Equal(t, "detail context", *node.Context)
		require.NoError(t, node.writable())
	}
	node, err := s.ResolveNode(ctx, fsID, mounts, Locator{Path: ptr("/drive/@" + artifact.String())})
	require.NoError(t, err)
	require.Equal(t, "ARTIFACT_READ_ONLY", reason(node.writable()))
	for _, locator := range []Locator{{Path: ptr("/drive/..")}, {Path: ptr("@" + file.String()), CwdID: &dir}, {NodeID: ptr(uuid.New())}} {
		_, err = s.ResolveNode(ctx, fsID, mounts, locator)
		require.Equal(t, codes.NotFound, status.Code(err))
	}
	_, err = s.ResolveNode(ctx, fsID, append(mounts, Mount{Path: "/drive/Việt", FilesystemID: uuid.New()}), Locator{Path: ptr("/drive/Việt/report.pdf")})
	require.Equal(t, "CROSS_FILESYSTEM_UNSUPPORTED", reason(err))
	_, err = s.GetNode(ctx, fsID, mounts, Locator{NodeID: &file, ExpectedNodeID: ptr(uuid.New())})
	require.Equal(t, "TARGET_MISMATCH", reason(err))
	nodes, err := s.BatchStat(ctx, fsID, mounts, []Locator{{NodeID: &file}, {NodeID: &artifact}, {NodeID: &file}})
	require.NoError(t, err)
	require.Equal(t, []uuid.UUID{file, artifact, file}, []uuid.UUID{nodes[0].ID, nodes[1].ID, nodes[2].ID})
	nodes, err = s.BatchStat(ctx, fsID, mounts, []Locator{{NodeID: &file}, {NodeID: ptr(uuid.New())}})
	require.Equal(t, codes.NotFound, status.Code(err))
	require.Nil(t, nodes, "batch failure must not return partial metadata")
	page, err := s.ListNodes(ctx, fsID, mounts, Locator{NodeID: &dir}, nil, nil)
	require.NoError(t, err)
	require.Len(t, page.Items, 1)
	require.Nil(t, page.Items[0].Context)
	require.Equal(t, "A report", *page.Items[0].Title)

	second := insert(dir, "second", "directory")
	page, err = s.ListNodes(ctx, fsID, mounts, Locator{NodeID: &dir}, nil, ptr(int32(1)))
	require.NoError(t, err)
	require.Equal(t, file, page.Items[0].ID)
	require.NotNil(t, page.NextCursor)
	next, err := s.ListNodes(ctx, fsID, mounts, Locator{NodeID: &dir}, page.NextCursor, ptr(int32(1)))
	require.NoError(t, err)
	require.Equal(t, second, next.Items[0].ID)
	require.Nil(t, next.NextCursor)
	_, err = s.ListNodes(ctx, fsID, mounts, Locator{NodeID: &root}, page.NextCursor, nil)
	require.Equal(t, codes.InvalidArgument, status.Code(err))

	_, err = s.GetBucketUsage(ctx, bucketID)
	require.Equal(t, codes.PermissionDenied, status.Code(err), "FS grant cannot inspect its bucket")
	testfixture.Grant(t, graph, "quota_bucket", bucketID, actor, authz.BucketRead)
	usage, err := s.GetBucketUsage(ctx, bucketID)
	require.NoError(t, err)
	require.EqualValues(t, 1024, usage.LimitBytes)
	_, err = s.GetNode(ctx, uuid.New(), []Mount{{Path: "/drive", FilesystemID: uuid.New()}}, Locator{NodeID: &file})
	require.Equal(t, codes.PermissionDenied, status.Code(err), "foreign target checks its own permission")

	_, err = db.Exec(ctx, `UPDATE nodes SET parent_id=NULL WHERE id=$1`, dir)
	require.NoError(t, err)
	for _, locator := range []Locator{{NodeID: &artifact}, {Path: ptr("/drive/@" + file.String())}, {Path: ptr("report.pdf"), CwdID: &dir}} {
		_, err = s.GetNode(ctx, fsID, mounts, locator)
		require.Equal(t, codes.NotFound, status.Code(err), "detached descendants stay hidden even by raw ID")
	}
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	_, err = s.GetFilesystem(canceled, fsID)
	require.ErrorIs(t, err, context.Canceled)
	require.NoError(t, server.Stop(t.Context(), nil))
	_, err = s.GetFilesystem(ctx, fsID)
	require.Equal(t, codes.Unavailable, status.Code(err), "graph outage never reuses previous allow")
}
