//go:build integration

package filesystem

import (
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"openlet/apps/letfs/internal/testfixture"
	"openlet/packages/go/authz"
	"openlet/packages/go/identity"
	sharedfixture "openlet/packages/go/testfixture"
)

func TestIntegrationDetachedArtifactCleanupPreservesTrashAndLiveRoots(t *testing.T) {
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
	mounts := []Mount{{Path: "/", FilesystemID: fs}}
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeCreate, authz.NodeRead, authz.ContentWrite, authz.NodeTrash)
	file, err := s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: "report.docx", File: &InlineFile{Content: []byte("old"), MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	trash, err := s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: "trash.bin", File: &InlineFile{Content: []byte("keep"), MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	entry, err := s.TrashNode(ctx, fs, mounts, Locator{NodeID: &trash.ID}, &trash.Revision)
	require.NoError(t, err)
	artifact, leaf := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'artifacts','directory',0),($4,$2,$1,'text.txt','file',8)`, artifact, fs, file.ID, leaf)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes,media_type) VALUES($1,'inline','obsolete','text/plain')`, leaf)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE filesystems SET node_count=node_count+2 WHERE id=$1`, fs)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE quota_buckets SET used_bytes=used_bytes+8 WHERE id=$1`, bucket)
	require.NoError(t, err)
	_, err = s.ReplaceContent(ctx, fs, mounts, Locator{NodeID: &file.ID}, &file.Revision, []byte("new"), "application/octet-stream")
	require.NoError(t, err)
	for _, expected := range []int{1, 1, 0} {
		count, err := s.DiscardForests(ctx)
		require.NoError(t, err)
		require.Equal(t, expected, count)
	}
	var used, nodes int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.EqualValues(t, 7, used)
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, fs).Scan(&nodes))
	require.EqualValues(t, 3, nodes)
	_, err = s.GetNode(ctx, fs, mounts, Locator{NodeID: created.RootID})
	require.NoError(t, err)
	var present bool
	require.NoError(t, db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM trash_entries WHERE id=$1 AND node_id=$2)`, entry.ID, trash.ID).Scan(&present))
	require.True(t, present)
}
