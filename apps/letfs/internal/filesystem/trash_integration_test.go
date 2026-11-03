//go:build integration

package filesystem

import (
	"encoding/json"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationReplacementAndTrashPreserveAccountingAndCleanup(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 64}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorID: actor, Gateway: true, Service: "gateway"})
	bucket, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateBucket(owner, uuid.New(), CreateBucket{ID: bucket, LimitBytes: 10})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, BucketID: bucket, RootName: "files"})
	require.NoError(t, err)
	root := *created.RootID
	mounts := []Mount{{Path: "/drive", FilesystemID: fs}}
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeCreate, authz.NodeRead, authz.NodeUpdate, authz.ContentWrite, authz.NodeTrash, authz.TrashRead, authz.TrashRestore)
	create := func(parent uuid.UUID, name string, file *InlineFile) Node {
		t.Helper()
		node, err := s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: &parent}, Name: name, File: file})
		require.NoError(t, err)
		return node
	}
	file := create(root, "source.pdf", &InlineFile{Content: []byte{0, 1, 2, 3, 255, 0}, MediaType: "application/pdf"})
	artifact := uuid.Must(uuid.NewV7())
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'report.md','file',3)`, artifact, fs, file.ID)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes) VALUES($1,'inline','old'::bytea)`, artifact)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE filesystems SET node_count=node_count+1 WHERE id=$1`, fs)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE quota_buckets SET used_bytes=used_bytes+3 WHERE id=$1`, bucket)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE files SET title='old title',context='old context',
 publication_status='ready' WHERE node_id=$1`, file.ID)
	require.NoError(t, err)
	_, err = s.ReplaceContent(ctx, fs, mounts, Locator{NodeID: &file.ID}, &file.Revision, []byte("1234567890"), "application/pdf")
	require.Equal(t, "QUOTA_EXCEEDED", reason(err))
	old, err := s.GetNode(ctx, fs, mounts, Locator{NodeID: &file.ID})
	require.NoError(t, err)
	require.Equal(t, "old context", *old.Context)
	require.Equal(t, file.Revision, old.Revision)
	_, err = s.GetNode(ctx, fs, mounts, Locator{NodeID: &artifact})
	require.NoError(t, err, "failed replacement cannot detach artifacts")

	// These rows represent a completed generation with a still outstanding ingest transfer.
	upload := uuid.Must(uuid.NewV7())
	_, err = db.Exec(ctx, `INSERT INTO uploads(id,filesystem_id,bucket_id,actor_id,input,transport,candidate_key,expected_size,content_md5,processing_file_id,processing_generation,relative_path,processing_stage,transfer_deadline)
 VALUES($1,$2,$3,$4,'{}','single','candidate/old',4,'CY9rzUYh03PK3k6DJie09g==',$5,1,'output.md','parse',now()+interval '1 hour')`, upload, fs, bucket, actor, file.ID)
	require.NoError(t, err)
	result, err := json.Marshal(Generation{FileID: file.ID, Generation: 1})
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) VALUES('test','process-file',$1,'hash',$2)`, uuid.NewString(), result)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE quota_buckets SET limit_bytes=1024 WHERE id=$1`, bucket)
	require.NoError(t, err)
	updated, err := s.ReplaceContent(ctx, fs, mounts, Locator{NodeID: &file.ID}, &file.Revision, []byte{255, 0, 13, 10}, "application/pdf")
	require.NoError(t, err)
	require.EqualValues(t, 2, updated.Revision)
	require.Nil(t, updated.Context)
	require.Nil(t, updated.Title)
	var bytes []byte
	var generation, used, count int64
	var state, publication string
	require.NoError(t, db.QueryRow(ctx, `SELECT inline_bytes,desired_generation,publication_status FROM files WHERE node_id=$1`, file.ID).Scan(&bytes, &generation, &publication))
	require.Equal(t, []byte{255, 0, 13, 10}, bytes)
	require.EqualValues(t, 2, generation)
	require.Equal(t, "pending", publication)
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.EqualValues(t, 7, used, "detached artifacts remain charged until physical metadata purge")
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, fs).Scan(&count))
	require.EqualValues(t, 3, count)
	_, err = s.GetNode(ctx, fs, mounts, Locator{NodeID: &artifact})
	require.Equal(t, apperr.Missing, apperr.KindOf(err))
	require.NoError(t, db.QueryRow(ctx, `SELECT state FROM uploads WHERE id=$1`, upload).Scan(&state))
	require.Equal(t, "aborted", state)
	var ambiguous bool
	var eligible, deadline time.Time
	require.NoError(t, db.QueryRow(ctx, `SELECT ambiguous_write,eligible_at FROM object_deletions WHERE object_key='candidate/old'`).Scan(&ambiguous, &eligible))
	require.True(t, ambiguous)
	require.NoError(t, db.QueryRow(ctx, `SELECT transfer_deadline FROM uploads WHERE id=$1`, upload).Scan(&deadline))
	require.False(t, eligible.Before(deadline), "cleanup cannot beat outstanding signed transfer deadline")
	var completed bool
	require.NoError(t, db.QueryRow(ctx, `SELECT expires_at IS NOT NULL FROM idempotency_keys WHERE operation='process-file'`).Scan(&completed))
	require.True(t, completed)
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM index_deletions WHERE file_id=$1 AND generation=1`, file.ID).Scan(&count))
	require.EqualValues(t, 1, count)
	_, err = s.ReplaceContent(ctx, fs, mounts, Locator{NodeID: &file.ID}, &file.Revision, []byte{1}, "application/pdf")
	require.Equal(t, "REVISION_MISMATCH", reason(err))

	entry, err := s.TrashNode(ctx, fs, mounts, Locator{NodeID: &file.ID}, &updated.Revision)
	require.NoError(t, err)
	require.Equal(t, actor, entry.ActorID)
	require.Equal(t, root, *entry.ParentID)
	_, err = s.GetNode(ctx, fs, mounts, Locator{NodeID: &file.ID})
	require.Equal(t, apperr.Missing, apperr.KindOf(err))
	readEntry, err := s.GetTrash(ctx, fs, entry.ID)
	require.NoError(t, err)
	require.Equal(t, entry, readEntry)
	page, err := s.ListTrash(ctx, fs, nil, nil)
	require.NoError(t, err)
	require.Len(t, page.Items, 1)
	require.NoError(t, db.QueryRow(ctx, `SELECT publication_status FROM files WHERE node_id=$1`, file.ID).Scan(&publication))
	require.Equal(t, "failed", publication)
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.EqualValues(t, 7, used)
	occupied := create(root, file.Name, nil)
	_, err = s.RestoreTrash(ctx, fs, entry.ID)
	require.Equal(t, "NAME_CONFLICT", reason(err))
	_, err = s.GetTrash(ctx, fs, entry.ID)
	require.NoError(t, err, "failed restore retains entry and its original name")
	_, err = s.UpdateNode(ctx, fs, mounts, UpdateNode{Locator: Locator{NodeID: &occupied.ID}, Revision: &occupied.Revision, Name: ptr("occupied-moved")})
	require.NoError(t, err)
	restored, err := s.RestoreTrash(ctx, fs, entry.ID)
	require.NoError(t, err)
	require.Equal(t, file.ID, restored.ID)
	require.Equal(t, file.Name, restored.Name)
	require.EqualValues(t, 4, restored.Revision)
	_, err = s.GetTrash(ctx, fs, entry.ID)
	require.Equal(t, apperr.Missing, apperr.KindOf(err))

	t.Run("separately trashed parent and concurrent restore", func(t *testing.T) {
		parent := create(root, "parent", nil)
		child := create(parent.ID, "child", nil)
		childEntry, err := s.TrashNode(ctx, fs, mounts, Locator{NodeID: &child.ID}, &child.Revision)
		require.NoError(t, err)
		parent, err = s.GetNode(ctx, fs, mounts, Locator{NodeID: &parent.ID})
		require.NoError(t, err)
		parentEntry, err := s.TrashNode(ctx, fs, mounts, Locator{NodeID: &parent.ID}, &parent.Revision)
		require.NoError(t, err)
		_, err = s.RestoreTrash(ctx, fs, childEntry.ID)
		require.Equal(t, apperr.Missing, apperr.KindOf(err))
		_, err = s.RestoreTrash(ctx, fs, parentEntry.ID)
		require.NoError(t, err)
		start, results := make(chan struct{}), make(chan error, 2)
		var workers sync.WaitGroup
		for range 2 {
			workers.Go(func() { <-start; _, err := s.RestoreTrash(ctx, fs, childEntry.ID); results <- err })
		}
		close(start)
		workers.Wait()
		close(results)
		accepted := 0
		for err := range results {
			if err == nil {
				accepted++
			} else {
				require.Equal(t, apperr.Missing, apperr.KindOf(err))
			}
		}
		require.Equal(t, 1, accepted)
		child, err = s.GetNode(ctx, fs, mounts, Locator{NodeID: &child.ID})
		require.NoError(t, err)
		entry, err := s.TrashNode(ctx, fs, mounts, Locator{NodeID: &child.ID}, &child.Revision)
		require.NoError(t, err)
		_, err = db.Exec(ctx, `UPDATE trash_entries SET state='purging' WHERE id=$1`, entry.ID)
		require.NoError(t, err)
		_, err = s.RestoreTrash(ctx, fs, entry.ID)
		require.Equal(t, "TRASH_PURGING", reason(err))
	})
}
