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

func TestIntegrationCrossScopeMoveRestoreAndBatchStat(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 1000, InlineLimit: 128, MaxFileBytes: 128}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	fs, source, destination := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 1000})
	require.NoError(t, err)
	a, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{source}, true, true)
	require.NoError(t, err)
	b, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{destination}, false, false)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", source, actor, authz.ScopeWrite)
	dir, err := s.CreateNode(ctx, source, uuid.New(), CreateNode{Parent: Locator{NodeID: a[0].RootID}, Name: "folder"})
	require.NoError(t, err)
	file, err := s.CreateNode(ctx, source, uuid.New(), CreateNode{Parent: Locator{NodeID: &dir.ID}, Name: "file.txt", File: &InlineFile{Content: []byte("hello"), MediaType: "text/plain"}})
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE files SET publication_status='ready',title='Kept title' WHERE node_id=$1`, file.ID)
	require.NoError(t, err)
	dir, err = s.GetNode(ctx, source, Locator{NodeID: &dir.ID})
	require.NoError(t, err)
	input := UpdateNode{Locator: Locator{NodeID: &dir.ID}, Revision: &dir.Revision, DestinationScopeID: &destination, Parent: &Locator{NodeID: b[0].RootID}}
	_, err = s.UpdateNode(ctx, source, input)
	require.Equal(t, "FORBIDDEN", reason(err))
	testfixture.Grant(t, graph, "scope", destination, actor, authz.ScopeWrite)
	var used, count int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes,node_count FROM filesystems WHERE id=$1`, fs).Scan(&used, &count))
	moved, err := s.UpdateNode(ctx, source, input)
	require.NoError(t, err)
	require.Equal(t, dir.ID, moved.ID)
	require.Equal(t, destination, moved.ScopeID)
	require.Equal(t, *b[0].RootID, *moved.ParentID)
	_, err = s.GetNode(ctx, source, Locator{NodeID: &file.ID})
	require.Equal(t, "NOT_FOUND", reason(err))
	child, err := s.GetNode(ctx, destination, Locator{Path: ptr("/folder/file.txt")})
	require.NoError(t, err)
	require.Equal(t, file.ID, child.ID)
	require.Equal(t, "Kept title", *child.Title)
	var generation int64
	var publication string
	require.NoError(t, db.QueryRow(ctx, `SELECT desired_generation,publication_status FROM files WHERE node_id=$1`, file.ID).Scan(&generation, &publication))
	require.EqualValues(t, 2, generation)
	require.Equal(t, "enriched", publication)
	_, err = s.PrepareEnrichment(ctx, Generation{FileID: file.ID, Generation: 1})
	require.Equal(t, "SOURCE_REPLACED", reason(err))
	var queued bool
	require.NoError(t, db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM index_deletions WHERE file_id=$1 AND generation=1)`, file.ID).Scan(&queued))
	require.True(t, queued)
	items, err := s.BatchStat(ctx, fs, []ScopedLocator{{ScopeID: source, Locator: Locator{Path: ptr("/")}}, {ScopeID: destination, Locator: Locator{NodeID: &file.ID}}, {ScopeID: destination, Locator: Locator{Path: ptr("/folder/file.txt")}}})
	require.NoError(t, err)
	require.Equal(t, []uuid.UUID{*a[0].RootID, file.ID, file.ID}, []uuid.UUID{items[0].ID, items[1].ID, items[2].ID})
	items, err = s.BatchStat(ctx, fs, []ScopedLocator{{ScopeID: source, Locator: Locator{NodeID: &file.ID}}})
	require.Equal(t, "NOT_FOUND", reason(err))
	require.Nil(t, items)
	entry, err := s.TrashNode(ctx, destination, Locator{NodeID: &moved.ID}, &moved.Revision)
	require.NoError(t, err)
	restored, err := s.RestoreTrash(ctx, destination, entry.ID, RestoreTrash{DestinationScopeID: &source, Parent: &Locator{NodeID: a[0].RootID}, Name: ptr("restored")})
	require.NoError(t, err)
	require.Equal(t, dir.ID, restored.ID)
	_, err = s.GetNode(ctx, source, Locator{Path: ptr("/restored/file.txt")})
	require.NoError(t, err)
	var afterUsed, afterCount int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes,node_count FROM filesystems WHERE id=$1`, fs).Scan(&afterUsed, &afterCount))
	require.Equal(t, used, afterUsed)
	require.Equal(t, count, afterCount)
	// A forbidden descendant rejects the entire transfer, including the root rename.
	_, err = s.CreateNode(ctx, source, uuid.New(), CreateNode{Parent: Locator{NodeID: &restored.ID}, Name: "binary", File: &InlineFile{Content: []byte{0, 255}, MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	restored, err = s.GetNode(ctx, source, Locator{NodeID: &restored.ID})
	require.NoError(t, err)
	_, err = s.UpdateNode(ctx, source, UpdateNode{Locator: Locator{NodeID: &restored.ID}, Revision: &restored.Revision, DestinationScopeID: &destination, Parent: &Locator{NodeID: b[0].RootID}, Name: ptr("rejected")})
	require.Equal(t, "BLOB_FILES_DISABLED", reason(err))
	unchanged, err := s.GetNode(ctx, source, Locator{NodeID: &restored.ID})
	require.NoError(t, err)
	require.Equal(t, restored, unchanged)
	otherFS, otherScope := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: otherFS, LimitBytes: 100})
	require.NoError(t, err)
	other, err := s.CreateScopes(owner, uuid.New(), otherFS, []uuid.UUID{otherScope}, true, true)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", otherScope, actor, authz.ScopeWrite)
	_, err = s.UpdateNode(ctx, source, UpdateNode{Locator: Locator{NodeID: &restored.ID}, Revision: &restored.Revision, DestinationScopeID: &otherScope, Parent: &Locator{NodeID: other[0].RootID}})
	require.Equal(t, "NOT_FOUND", reason(err))
	items, err = s.BatchStat(ctx, fs, []ScopedLocator{{ScopeID: otherScope, Locator: Locator{Path: ptr("/")}}})
	require.Equal(t, "NOT_FOUND", reason(err))
	require.Nil(t, items)
}
