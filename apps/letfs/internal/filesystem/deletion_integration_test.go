//go:build integration

package filesystem

import (
	"fmt"
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"openlet/apps/letfs/internal/testfixture"
	"openlet/packages/go/authz"
	"openlet/packages/go/identity"
	sharedfixture "openlet/packages/go/testfixture"
)

func TestIntegrationDeletionBatchesRetainEvidenceAndDebitOnce(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 200, InlineLimit: 64, MaxFileBytes: 64}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	bucket, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateBucket(owner, uuid.New(), CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	root := *created.RootID
	mounts := []Mount{{Path: "/drive", FilesystemID: fs}}
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeCreate, authz.NodeRead, authz.NodeTrash, authz.TrashRestore, authz.TrashRead)
	create := func(parent uuid.UUID, name string, file *InlineFile) Node {
		t.Helper()
		node, err := s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: &parent}, Name: name, File: file})
		require.NoError(t, err)
		return node
	}
	folder := create(root, "purge", nil)
	for i := range 70 {
		create(folder.ID, fmt.Sprintf("%03d.bin", i), &InlineFile{Content: []byte("x"), MediaType: "application/octet-stream"})
	}
	outside := create(root, "outside.bin", &InlineFile{Content: []byte("keep"), MediaType: "application/octet-stream"})
	folder, err = s.GetNode(ctx, fs, mounts, Locator{NodeID: &folder.ID})
	require.NoError(t, err)
	entry, err := s.TrashNode(ctx, fs, mounts, Locator{NodeID: &folder.ID}, &folder.Revision)
	require.NoError(t, err)
	_, err = s.PrepareTrashPurge(ctx, fs, entry.ID)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.TrashPurge)
	admitted, err := s.PrepareTrashPurge(ctx, fs, entry.ID)
	require.NoError(t, err)
	require.Equal(t, "purging", admitted.Status)
	_, err = s.RestoreTrash(ctx, fs, entry.ID)
	require.Equal(t, "TRASH_PURGING", reason(err))
	done, err := s.DeletionBatch(ctx, fs, &entry.ID)
	require.NoError(t, err)
	require.False(t, done)
	var used, count int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.EqualValues(t, 10, used)
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM nodes WHERE parent_id=$1`, folder.ID).Scan(&count))
	require.EqualValues(t, 6, count)
	_, err = s.PrepareTrashPurge(ctx, fs, entry.ID)
	require.NoError(t, err)
	var workers sync.WaitGroup
	results := make(chan error, 3)
	for range 3 {
		workers.Go(func() { _, err := s.DeletionBatch(ctx, fs, &entry.ID); results <- err })
	}
	workers.Wait()
	close(results)
	for err := range results {
		require.NoError(t, err)
	}
	done, err = s.DeletionBatch(ctx, fs, &entry.ID)
	require.NoError(t, err)
	require.True(t, done)
	admitted, err = s.PrepareTrashPurge(ctx, fs, entry.ID)
	require.NoError(t, err)
	require.Nil(t, admitted)
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.EqualValues(t, 4, used)
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, fs).Scan(&count))
	require.EqualValues(t, 2, count)
	_, err = s.GetNode(ctx, fs, mounts, Locator{NodeID: &outside.ID})
	require.NoError(t, err)

	// Full deletion fences outstanding writes, retains cleanup and leaves a stable tombstone.
	upload := uuid.Must(uuid.NewV7())
	_, err = db.Exec(ctx, `INSERT INTO uploads(id,filesystem_id,bucket_id,actor_id,input,transport,candidate_key,expected_size,content_md5,write_expires_at,transfer_deadline)
 VALUES($1,$2,$3,$4,'{}','single','candidate/delete',4,'CY9rzUYh03PK3k6DJie09g==',now()+interval '1 hour',now()+interval '2 hours')`, upload, fs, bucket, actor)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE files SET storage_kind='object',inline_bytes=NULL,object_key='objects/delete',
 embedding_model='model',vector_collection='collection',vector_dimension=3 WHERE node_id=$1`, outside.ID)
	require.NoError(t, err)
	foreign := identity.WithPrincipal(t.Context(), identity.Principal{Service: "other-owner"})
	require.Equal(t, codes.NotFound, status.Code(s.PrepareFilesystemDeletion(foreign, fs)))
	require.Equal(t, codes.PermissionDenied, status.Code(s.PrepareFilesystemDeletion(ctx, fs)))
	done, err = s.DeletionBatch(ctx, fs, nil)
	require.Equal(t, "FILESYSTEM_NOT_DELETING", reason(err))
	require.False(t, done)
	_, err = s.FreezeBucket(owner, uuid.New(), bucket)
	require.NoError(t, err)
	require.NoError(t, s.PrepareFilesystemDeletion(owner, fs))
	require.NoError(t, s.PrepareFilesystemDeletion(owner, fs))
	var state string
	require.NoError(t, db.QueryRow(ctx, `SELECT state FROM uploads WHERE id=$1`, upload).Scan(&state))
	require.Equal(t, "aborted", state)
	var safe bool
	require.NoError(t, db.QueryRow(ctx, `SELECT ambiguous_write AND eligible_at >= (SELECT transfer_deadline FROM uploads WHERE id=$1) FROM object_deletions WHERE object_key='candidate/delete'`, upload).Scan(&safe))
	require.True(t, safe)
	for range 3 {
		done, err = s.DeletionBatch(ctx, fs, nil)
		require.NoError(t, err)
		if done {
			break
		}
	}
	require.True(t, done)
	done, err = s.DeletionBatch(ctx, fs, nil)
	require.NoError(t, err)
	require.True(t, done)
	require.NoError(t, db.QueryRow(ctx, `SELECT state,node_count FROM filesystems WHERE id=$1 AND root_id IS NULL`, fs).Scan(&state, &count))
	require.Equal(t, "deleted", state)
	require.Zero(t, count)
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.Zero(t, used)
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM object_deletions WHERE object_key='objects/delete'`).Scan(&count))
	require.EqualValues(t, 1, count)
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM index_deletions WHERE file_id=$1`, outside.ID).Scan(&count))
	require.EqualValues(t, 1, count)
	_, err = s.CompleteBucketDeletion(owner, uuid.New(), bucket)
	require.NoError(t, err)
	_, err = s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.Error(t, err)
}
