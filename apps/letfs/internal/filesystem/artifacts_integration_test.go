//go:build integration

package filesystem

import (
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationDetachedArtifactCleanupPreservesTrashAndLiveRoots(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 64}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	filesystemID, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: filesystemID, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := createTestScope(owner, &s, uuid.New(), filesystemID, fs)
	require.NoError(t, err)

	testfixture.Grant(t, graph, "scope", fs, actor, authz.ScopeWrite, authz.ScopeReadMetadata, authz.ScopeWrite, authz.ScopeTrash)
	file, err := s.CreateNode(ctx, fs, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: "report.docx", File: &InlineFile{Content: []byte("old"), MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	trash, err := s.CreateNode(ctx, fs, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: "trash.bin", File: &InlineFile{Content: []byte("keep"), MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	entry, err := s.TrashNode(ctx, fs, Locator{NodeID: &trash.ID}, &trash.Revision)
	require.NoError(t, err)
	artifact, leaf := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'artifacts','directory',0),($4,$2,$1,'text.txt','file',8)`, artifact, fs, file.ID, leaf)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes,media_type) VALUES($1,'inline','obsolete','text/plain')`, leaf)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE filesystems SET node_count=node_count+2 WHERE id=$1`, filesystemID)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE filesystems SET used_bytes=used_bytes+8 WHERE id=$1`, filesystemID)
	require.NoError(t, err)
	_, err = s.ReplaceContent(ctx, fs, Locator{NodeID: &file.ID}, &file.Revision, []byte("new"), "application/octet-stream")
	require.NoError(t, err)
	for _, expected := range []int{1, 1, 0} {
		count, err := s.DiscardForests(ctx)
		require.NoError(t, err)
		require.Equal(t, expected, count)
	}
	var used, nodes int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM filesystems WHERE id=$1`, filesystemID).Scan(&used))
	require.EqualValues(t, 7, used)
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, filesystemID).Scan(&nodes))
	require.EqualValues(t, 3, nodes)
	_, err = s.GetNode(ctx, fs, Locator{NodeID: created.RootID})
	require.NoError(t, err)
	var present bool
	require.NoError(t, db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM trash_entries WHERE id=$1 AND node_id=$2)`, entry.ID, trash.ID).Scan(&present))
	require.True(t, present)
}
