//go:build integration

package filesystem

import (
	"crypto/sha256"
	"encoding/hex"
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

func TestIntegrationCopyAdmissionCapturesIdentityAndReplaysWithoutMutation(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, MaxCopyNodes: 64, InlineLimit: 64, MaxFileBytes: 64, MaxOutstanding: 10, MaxCleanupBacklog: 10}
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
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeCreate, authz.CopyCreate, authz.ContentWrite, authz.NodeTrash)
	bytes := []byte{0, 255, 13, 10}
	source, err := s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: &root}, Name: "source.bin", File: &InlineFile{Content: bytes, MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	input := CreateCopy{SourceID: source.ID, ParentID: root, Name: "copy.bin", Revision: &source.Revision}
	key := uuid.New()
	_, err = s.AdmitCopy(ctx, fs, mounts, key, input)
	require.Equal(t, apperr.Forbidden, apperr.KindOf(err), "copy_create does not imply source read")
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeRead)
	var workers sync.WaitGroup
	results := make(chan CopyAdmission, 6)
	failures := make(chan error, 6)
	for range 6 {
		workers.Go(func() {
			admission, err := s.AdmitCopy(ctx, fs, mounts, key, input)
			results <- admission
			failures <- err
		})
	}
	workers.Wait()
	close(results)
	close(failures)
	for err := range failures {
		require.NoError(t, err)
	}
	var admission CopyAdmission
	for result := range results {
		if admission.ID == uuid.Nil {
			admission = result
		}
		require.Equal(t, admission, result)
	}
	require.Equal(t, actor, admission.ActorID)
	require.Equal(t, fs, admission.FilesystemID)
	require.Equal(t, copyDestination(admission.ID, source.ID), admission.Root.Destination)
	require.Equal(t, source.Revision, admission.Root.Revision)
	digest := sha256.Sum256(bytes)
	require.Equal(t, hex.EncodeToString(digest[:]), *admission.Root.InlineSHA256)
	require.Nil(t, admission.Root.ObjectKey)
	require.EqualValues(t, 64, admission.MaxNodes)
	require.EqualValues(t, 1000, admission.MaxBytes)
	var used, count int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.EqualValues(t, 4, used)
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, fs).Scan(&count))
	require.EqualValues(t, 2, count)
	var visible bool
	require.NoError(t, db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM nodes WHERE id=$1)`, admission.Root.Destination).Scan(&visible))
	require.False(t, visible, "admission does not fabricate completed copy")
	changed := input
	changed.Name = "different"
	_, err = s.AdmitCopy(ctx, fs, mounts, key, changed)
	require.Equal(t, "IDEMPOTENCY_CONFLICT", reason(err))
	limited := s
	limited.MaxOutstanding = 1
	_, err = limited.AdmitCopy(ctx, fs, mounts, uuid.New(), input)
	require.Equal(t, "RESOURCE_LIMIT", reason(err))
	_, err = limited.AdmitCopy(ctx, fs, mounts, key, input)
	require.NoError(t, err, "saved admission precedes changed operation limits")
	invalid := input
	invalid.Revision = nil
	_, err = s.AdmitCopy(ctx, fs, mounts, uuid.New(), invalid)
	require.Equal(t, "PRECONDITION_REQUIRED", reason(err))
	invalid = input
	invalid.Name = source.Name
	_, err = s.AdmitCopy(ctx, fs, mounts, uuid.New(), invalid)
	require.Equal(t, "NAME_CONFLICT", reason(err))
	invalid = input
	invalid.SourceID = root
	rootNode, err := s.GetNode(ctx, fs, mounts, Locator{NodeID: &root})
	require.NoError(t, err)
	invalid.Revision = &rootNode.Revision
	_, err = s.AdmitCopy(ctx, fs, mounts, uuid.New(), invalid)
	require.Equal(t, "CYCLE", reason(err))
	updated, err := s.ReplaceContent(ctx, fs, mounts, Locator{NodeID: &source.ID}, &source.Revision, []byte("changed"), "application/octet-stream")
	require.NoError(t, err)
	_, err = s.AdmitCopy(ctx, fs, mounts, uuid.New(), input)
	require.Equal(t, "REVISION_MISMATCH", reason(err))
	replay, err := s.AdmitCopy(ctx, fs, mounts, key, input)
	require.NoError(t, err)
	require.Equal(t, admission, replay)
	_, err = s.TrashNode(ctx, fs, mounts, Locator{NodeID: &source.ID}, &updated.Revision)
	require.NoError(t, err)
	replay, err = s.AdmitCopy(ctx, fs, mounts, key, input)
	require.NoError(t, err)
	require.Equal(t, admission, replay, "lost reply returns immutable admission after source disappears")
	_, err = s.AdmitCopy(ctx, fs, mounts, uuid.New(), input)
	require.Equal(t, apperr.Missing, apperr.KindOf(err))
}
