//go:build integration

package filesystem

import (
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationNativeDirectories(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 64}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: actor, Service: "gateway", Gateway: true})
	fs, scope := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 1024})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{scope}, true, true)
	require.NoError(t, err)
	root := *scopes[0].RootID
	testfixture.Grant(t, graph, "scope", scope, actor, authz.ScopeWrite)
	parent := Locator{Path: ptr("/"), ExpectedParentID: &root, RootID: &root}
	leaf, err := s.CreateDirectories(ctx, scope, parent, []string{"a", "b", "c"}, true)
	require.NoError(t, err)
	replayed, err := s.CreateDirectories(ctx, scope, parent, []string{"a", "b", "c"}, true)
	require.NoError(t, err)
	require.Equal(t, leaf.ID, replayed.ID)
	require.Equal(t, leaf.Revision, replayed.Revision)
	_, err = s.CreateDirectories(ctx, scope, parent, []string{"a"}, false)
	require.Equal(t, "NAME_CONFLICT", reason(err))
	_, err = s.CreateDirectories(ctx, scope, parent, []string{"x", "y"}, false)
	require.Equal(t, "VALIDATION", reason(err))
	_, err = s.CreateDirectories(ctx, scope, parent, []string{"x", ".."}, true)
	require.Equal(t, "VALIDATION", reason(err))
	_, err = s.ResolveNode(ctx, scope, Locator{Path: ptr("/x")})
	require.Equal(t, "NOT_FOUND", reason(err))
	_, err = s.CreateDirectories(ctx, scope, parent, []string{"@" + uuid.NewString()}, true)
	require.Equal(t, "VALIDATION", reason(err))
	_, err = s.CreateDirectories(ctx, scope, Locator{Path: ptr("/")}, []string{"unguarded"}, true)
	require.Equal(t, "PRECONDITION_REQUIRED", reason(err))
	box, err := s.CreateDirectories(ctx, scope, parent, []string{"box"}, false)
	require.NoError(t, err)
	_, err = s.CreateDirectories(ctx, scope, Locator{NodeID: &root, RootID: &box.ID}, []string{"escape"}, false)
	require.Equal(t, "NOT_FOUND", reason(err))
	_, err = s.TrashNode(ctx, scope, Locator{NodeID: &box.ID, RootID: &box.ID}, &box.Revision, true)
	require.Equal(t, "ROOT_IMMUTABLE", reason(err))
	// Any failure during parent creation rolls back every earlier directory and node count.
	var count int64
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, fs).Scan(&count))
	s.MaxNodes = count + 1
	_, err = s.CreateDirectories(ctx, scope, parent, []string{"rollback", "child"}, true)
	require.Equal(t, "RESOURCE_LIMIT", reason(err))
	_, err = s.ResolveNode(ctx, scope, Locator{Path: ptr("/rollback")})
	require.Equal(t, "NOT_FOUND", reason(err))
	var current int64
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, fs).Scan(&current))
	require.Equal(t, count, current)
	s.MaxNodes = 100
	file, err := s.CreateNode(ctx, scope, uuid.New(), CreateNode{Parent: Locator{NodeID: &root}, Name: "file.txt", File: &InlineFile{Content: []byte("hello"), MediaType: "text/plain"}})
	require.NoError(t, err)
	_, err = s.CreateDirectories(ctx, scope, parent, []string{"file.txt", "child"}, true)
	require.Equal(t, "NOT_DIRECTORY", reason(err))
	_, err = s.TrashNode(ctx, scope, Locator{NodeID: &file.ID}, &file.Revision, true)
	require.Equal(t, "NOT_DIRECTORY", reason(err))
	// Rmdir and child creation share the filesystem/scope lock: neither can silently lose a child.
	for range 4 {
		dir, err := s.CreateDirectories(ctx, scope, parent, []string{uuid.NewString()}, false)
		require.NoError(t, err)
		start := make(chan struct{})
		var wg sync.WaitGroup
		var createErr, trashErr error
		var child Node
		var entry TrashEntry
		wg.Go(func() {
			<-start
			child, createErr = s.CreateDirectories(ctx, scope, Locator{NodeID: &dir.ID}, []string{"child"}, false)
		})
		wg.Go(func() {
			<-start
			entry, trashErr = s.TrashNode(ctx, scope, Locator{NodeID: &dir.ID}, &dir.Revision, true)
		})
		close(start)
		wg.Wait()
		if trashErr == nil {
			require.Equal(t, "NOT_FOUND", reason(createErr))
			require.Equal(t, dir.ID, entry.NodeID)
		} else {
			require.NoError(t, createErr)
			require.Equal(t, "REVISION_MISMATCH", reason(trashErr))
			live, err := s.ResolveNode(ctx, scope, Locator{NodeID: &dir.ID})
			require.NoError(t, err)
			_, err = s.TrashNode(ctx, scope, Locator{NodeID: &dir.ID}, &live.Revision, true)
			require.Equal(t, "DIRECTORY_NOT_EMPTY", reason(err))
			liveChild, err := s.ResolveNode(ctx, scope, Locator{NodeID: &child.ID})
			require.NoError(t, err)
			require.Equal(t, dir.ID, *liveChild.ParentID)
		}
	}
	// Native empty-directory trash is ordinary restorable trash and does not release bytes.
	entry, err := s.TrashNode(ctx, scope, Locator{NodeID: &leaf.ID}, &leaf.Revision, true)
	require.NoError(t, err)
	restored, err := s.RestoreTrash(ctx, scope, entry.ID, RestoreTrash{})
	require.NoError(t, err)
	require.Equal(t, leaf.ID, restored.ID)
}
