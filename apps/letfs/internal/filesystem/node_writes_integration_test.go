//go:build integration

package filesystem

import (
	"bytes"
	"fmt"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationNodeWritesReceiptsQuotaAndTreeGuards(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 1000, InlineLimit: 256, MaxFileBytes: 128}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	newFS := func(limit int64) (uuid.UUID, uuid.UUID, uuid.UUID) {
		t.Helper()
		bucket, id := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
		_, err := s.CreateBucket(owner, uuid.New(), CreateBucket{ID: bucket, LimitBytes: limit})
		require.NoError(t, err)
		fs, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: id, BucketID: bucket, RootName: "files"})
		require.NoError(t, err)
		testfixture.Grant(t, graph, "filesystem", id, actor, authz.NodeCreate, authz.NodeUpdate, authz.NodeRead, authz.NodeResolve, authz.NodeList)
		return bucket, id, *fs.RootID
	}
	mounts := func(fs uuid.UUID) []Mount { return []Mount{{Path: "/drive", FilesystemID: fs}} }
	create := func(fs, parent uuid.UUID, name string, file *InlineFile) Node {
		t.Helper()
		node, err := s.CreateNode(ctx, fs, mounts(fs), uuid.New(), CreateNode{Parent: Locator{NodeID: &parent}, Name: name, File: file})
		require.NoError(t, err)
		return node
	}
	concurrent := func(run func(int) (Node, error)) ([]Node, []error) {
		t.Helper()
		start := make(chan struct{})
		var workers sync.WaitGroup
		nodes, errs := make([]Node, 8), make([]error, 8)
		for i := range 8 {
			workers.Go(func() { <-start; nodes[i], errs[i] = run(i) })
		}
		close(start)
		workers.Wait()
		return nodes, errs
	}
	bucket, fs, root := newFS(1024)
	content := []byte{0, 255, 10, 13, 1, 0}
	input := CreateNode{Parent: Locator{NodeID: &root}, Name: "document.PDF", File: &InlineFile{Content: content, MediaType: "application/pdf"}}
	key := uuid.New()
	nodes, errs := concurrent(func(int) (Node, error) { return s.CreateNode(ctx, fs, mounts(fs), key, input) })
	for i, err := range errs {
		require.NoError(t, err)
		require.Equal(t, nodes[0].ID, nodes[i].ID)
	}
	file := nodes[0]
	var saved []byte
	var generation, used, count int64
	var publication, format string
	require.NoError(t, db.QueryRow(ctx, `SELECT inline_bytes,desired_generation,publication_status,processing_format FROM files WHERE node_id=$1`, file.ID).Scan(&saved, &generation, &publication, &format))
	require.Equal(t, content, saved)
	require.EqualValues(t, 1, generation)
	require.Equal(t, "pending", publication)
	require.Equal(t, "pdf", format)
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.EqualValues(t, len(content), used)
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, fs).Scan(&count))
	require.EqualValues(t, 2, count)
	input.Name = "different"
	_, err := s.CreateNode(ctx, fs, mounts(fs), key, input)
	require.Equal(t, "IDEMPOTENCY_CONFLICT", reason(err))
	_, err = s.CreateNode(ctx, fs, mounts(fs), uuid.New(), CreateNode{Parent: Locator{NodeID: &root}, Name: file.Name, File: input.File})
	require.Equal(t, "NAME_CONFLICT", reason(err))
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, fs).Scan(&count))
	require.EqualValues(t, 2, count, "failed insert rolls back node and quota increments")

	emptyKey := uuid.New()
	empty := CreateNode{Parent: Locator{NodeID: &root}, Name: "empty.bin", File: &InlineFile{MediaType: "application/octet-stream"}}
	first, err := s.CreateNode(ctx, fs, mounts(fs), emptyKey, empty)
	require.NoError(t, err)
	empty.File.Content = []byte{}
	replayed, err := s.CreateNode(ctx, fs, mounts(fs), emptyKey, empty)
	require.NoError(t, err)
	require.Equal(t, first.ID, replayed.ID, "empty protobuf bytes have one receipt identity")
	require.NoError(t, db.QueryRow(ctx, `SELECT inline_bytes FROM files WHERE node_id=$1`, first.ID).Scan(&saved))
	require.NotNil(t, saved)
	require.Empty(t, saved)
	_, err = s.CreateNode(ctx, fs, mounts(fs), uuid.New(), CreateNode{Parent: Locator{NodeID: &root}, Name: "too-big", File: &InlineFile{Content: bytes.Repeat([]byte{1}, 129), MediaType: "text/plain"}})
	require.Equal(t, "REQUEST_LIMIT", reason(err))
	_, err = s.CreateNode(ctx, fs, mounts(fs), uuid.New(), CreateNode{Parent: Locator{NodeID: &root}, Name: "@" + uuid.NewString()})
	require.Equal(t, apperr.Invalid, apperr.KindOf(err))
	_, err = s.CreateNode(ctx, fs, mounts(fs), uuid.New(), CreateNode{Parent: Locator{Path: ptr("/drive")}, Name: "guarded"})
	require.Equal(t, "PRECONDITION_REQUIRED", reason(err))

	dir := create(fs, root, "target", nil)
	_, err = s.UpdateNode(ctx, fs, mounts(fs), UpdateNode{Locator: Locator{NodeID: &file.ID}, Name: ptr("renamed.pdf")})
	require.Equal(t, "PRECONDITION_REQUIRED", reason(err))
	moved, err := s.UpdateNode(ctx, fs, mounts(fs), UpdateNode{Locator: Locator{NodeID: &file.ID}, Revision: &file.Revision, Name: ptr("renamed.pdf"), Parent: &Locator{NodeID: &dir.ID}})
	require.NoError(t, err)
	require.Equal(t, dir.ID, *moved.ParentID)
	require.EqualValues(t, 2, moved.Revision)
	_, err = s.UpdateNode(ctx, fs, mounts(fs), UpdateNode{Locator: Locator{NodeID: &file.ID}, Revision: &file.Revision, Name: ptr("stale")})
	require.Equal(t, "REVISION_MISMATCH", reason(err))
	_, err = s.UpdateNode(ctx, fs, mounts(fs), UpdateNode{Locator: Locator{Path: ptr("/drive/target/renamed.pdf"), ExpectedNodeID: ptr(uuid.New())}, Revision: &moved.Revision, Name: ptr("wrong")})
	require.Equal(t, "TARGET_MISMATCH", reason(err))
	child := create(fs, dir.ID, "child", nil)
	dir, err = s.GetNode(ctx, fs, mounts(fs), Locator{NodeID: &dir.ID})
	require.NoError(t, err)
	_, err = s.UpdateNode(ctx, fs, mounts(fs), UpdateNode{Locator: Locator{NodeID: &dir.ID}, Revision: &dir.Revision, Parent: &Locator{NodeID: &child.ID}})
	require.Equal(t, "CYCLE", reason(err))
	_, err = s.UpdateNode(ctx, fs, mounts(fs), UpdateNode{Locator: Locator{NodeID: &dir.ID}, Revision: &dir.Revision, Parent: &Locator{NodeID: &file.ID}})
	require.Equal(t, "NOT_DIRECTORY", reason(err))
	rootNode, err := s.GetNode(ctx, fs, mounts(fs), Locator{NodeID: &root})
	require.NoError(t, err)
	_, err = s.UpdateNode(ctx, fs, mounts(fs), UpdateNode{Locator: Locator{NodeID: &root}, Revision: &rootNode.Revision, Name: ptr("changed")})
	require.Equal(t, "ROOT_IMMUTABLE", reason(err))

	artifact := uuid.Must(uuid.NewV7())
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind) VALUES($1,$2,$3,'artifact','directory')`, artifact, fs, moved.ID)
	require.NoError(t, err)
	_, err = s.UpdateNode(ctx, fs, mounts(fs), UpdateNode{Locator: Locator{NodeID: &artifact}, Revision: ptr(int64(1)), Name: ptr("mutable")})
	require.Equal(t, "ARTIFACT_READ_ONLY", reason(err))
	_, err = s.CreateNode(ctx, fs, mounts(fs), uuid.New(), CreateNode{Parent: Locator{NodeID: &artifact}, Name: "mutable"})
	require.Equal(t, "ARTIFACT_READ_ONLY", reason(err))

	t.Run("shared bucket quota and node limits serialize", func(t *testing.T) {
		bucket, firstFS, firstRoot := newFS(10)
		secondFS, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: uuid.Must(uuid.NewV7()), BucketID: bucket, RootName: "second"})
		require.NoError(t, err)
		testfixture.Grant(t, graph, "filesystem", secondFS.ID, actor, authz.NodeCreate)
		_, errs := concurrent(func(i int) (Node, error) {
			fs, root := firstFS, firstRoot
			if i%2 == 1 {
				fs, root = secondFS.ID, *secondFS.RootID
			}
			return s.CreateNode(ctx, fs, mounts(fs), uuid.New(), CreateNode{Parent: Locator{NodeID: &root}, Name: fmt.Sprint(i), File: &InlineFile{Content: content, MediaType: "application/octet-stream"}})
		})
		accepted := 0
		for _, err := range errs {
			if err == nil {
				accepted++
			} else {
				require.Equal(t, "QUOTA_EXCEEDED", reason(err))
			}
		}
		require.Equal(t, 1, accepted)
		require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
		require.EqualValues(t, 6, used)
		_, limitedFS, limitedRoot := newFS(10)
		previousMaxNodes := s.MaxNodes
		t.Cleanup(func() { s.MaxNodes = previousMaxNodes })
		s.MaxNodes = 2
		_, errs = concurrent(func(i int) (Node, error) {
			return s.CreateNode(ctx, limitedFS, mounts(limitedFS), uuid.New(), CreateNode{Parent: Locator{NodeID: &limitedRoot}, Name: fmt.Sprint(i)})
		})
		accepted = 0
		for _, err := range errs {
			if err == nil {
				accepted++
			} else {
				require.Equal(t, "RESOURCE_LIMIT", reason(err))
			}
		}
		require.Equal(t, 1, accepted)
		require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, limitedFS).Scan(&count))
		require.EqualValues(t, 2, count)
	})

	t.Run("maximum tree depth", func(t *testing.T) {
		_, fs, root := newFS(100)
		parent := root
		for range 128 {
			node := create(fs, parent, "level", nil)
			parent = node.ID
		}
		_, err := s.CreateNode(ctx, fs, mounts(fs), uuid.New(), CreateNode{Parent: Locator{NodeID: &parent}, Name: "too-deep"})
		require.Equal(t, "RESOURCE_LIMIT", reason(err))
		branch := create(fs, root, "branch", nil)
		create(fs, branch.ID, "leaf", nil)
		branch, err = s.GetNode(ctx, fs, mounts(fs), Locator{NodeID: &branch.ID})
		require.NoError(t, err)
		_, err = s.UpdateNode(ctx, fs, mounts(fs), UpdateNode{Locator: Locator{NodeID: &branch.ID}, Revision: &branch.Revision, Parent: &Locator{NodeID: &parent}})
		require.Equal(t, "RESOURCE_LIMIT", reason(err), "moving a subtree checks its complete height")
	})
}
