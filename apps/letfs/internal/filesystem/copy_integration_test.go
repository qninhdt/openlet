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
	filesystemID, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: filesystemID, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := createTestScope(owner, &s, uuid.New(), filesystemID, fs)
	require.NoError(t, err)
	root := *created.RootID

	testfixture.Grant(t, graph, "scope", fs, actor, authz.ScopeWrite, authz.ScopeWrite, authz.ScopeWrite, authz.ScopeTrash)
	bytes := []byte{0, 255, 13, 10}
	source, err := s.CreateNode(ctx, fs, uuid.New(), CreateNode{Parent: Locator{NodeID: &root}, Name: "source.bin", File: &InlineFile{Content: bytes, MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	input := CreateCopy{DestinationScopeID: fs, SourceID: source.ID, ParentID: root, Name: "copy.bin", Revision: &source.Revision}
	key := uuid.New()
	var workers sync.WaitGroup
	results := make(chan CopyAdmission, 6)
	failures := make(chan error, 6)
	for range 6 {
		workers.Go(func() {
			admission, err := s.AdmitCopy(ctx, fs, key, input)
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
	require.Equal(t, filesystemID, admission.FilesystemID)
	require.Equal(t, fs, admission.ScopeID)
	require.Equal(t, copyDestination(admission.ID, source.ID), admission.Root.Destination)
	require.Equal(t, source.Revision, admission.Root.Revision)
	digest := sha256.Sum256(bytes)
	require.Equal(t, hex.EncodeToString(digest[:]), *admission.Root.InlineSHA256)
	require.Nil(t, admission.Root.ObjectKey)
	require.EqualValues(t, 64, admission.MaxNodes)
	require.EqualValues(t, 1000, admission.MaxBytes)
	var used, count int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM filesystems WHERE id=$1`, filesystemID).Scan(&used))
	require.EqualValues(t, 4, used)
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, filesystemID).Scan(&count))
	require.EqualValues(t, 2, count)
	var visible bool
	require.NoError(t, db.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM nodes WHERE id=$1)`, admission.Root.Destination).Scan(&visible))
	require.False(t, visible, "admission does not fabricate completed copy")
	changed := input
	changed.Name = "different"
	_, err = s.AdmitCopy(ctx, fs, key, changed)
	require.Equal(t, "IDEMPOTENCY_CONFLICT", reason(err))
	limited := s
	limited.MaxOutstanding = 1
	_, err = limited.AdmitCopy(ctx, fs, uuid.New(), input)
	require.Equal(t, "RESOURCE_LIMIT", reason(err))
	_, err = limited.AdmitCopy(ctx, fs, key, input)
	require.NoError(t, err, "saved admission precedes changed operation limits")
	invalid := input
	invalid.Revision = nil
	_, err = s.AdmitCopy(ctx, fs, uuid.New(), invalid)
	require.Equal(t, "PRECONDITION_REQUIRED", reason(err))
	invalid = input
	invalid.Name = source.Name
	_, err = s.AdmitCopy(ctx, fs, uuid.New(), invalid)
	require.Equal(t, "NAME_CONFLICT", reason(err))
	invalid = input
	invalid.SourceID = root
	rootNode, err := s.GetNode(ctx, fs, Locator{NodeID: &root})
	require.NoError(t, err)
	invalid.Revision = &rootNode.Revision
	_, err = s.AdmitCopy(ctx, fs, uuid.New(), invalid)
	require.Equal(t, "CYCLE", reason(err))
	updated, err := s.ReplaceContent(ctx, fs, Locator{NodeID: &source.ID}, &source.Revision, []byte("changed"), "application/octet-stream")
	require.NoError(t, err)
	_, err = s.AdmitCopy(ctx, fs, uuid.New(), input)
	require.Equal(t, "REVISION_MISMATCH", reason(err))
	replay, err := s.AdmitCopy(ctx, fs, key, input)
	require.NoError(t, err)
	require.Equal(t, admission, replay)
	_, err = s.TrashNode(ctx, fs, Locator{NodeID: &source.ID}, &updated.Revision)
	require.NoError(t, err)
	replay, err = s.AdmitCopy(ctx, fs, key, input)
	require.NoError(t, err)
	require.Equal(t, admission, replay, "lost reply returns immutable admission after source disappears")
	_, err = s.AdmitCopy(ctx, fs, uuid.New(), input)
	require.Equal(t, apperr.Missing, apperr.KindOf(err))
}

func TestIntegrationCrossScopeCopyUsesSeparateGrantsAndOneQuota(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, MaxCopyNodes: 100, InlineLimit: 64, MaxFileBytes: 64, MaxOutstanding: 10, MaxCleanupBacklog: 10}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "workspace"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	fs, sourceScope, destinationScope := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 6})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{sourceScope, destinationScope}, true, true)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", sourceScope, actor, authz.ScopeWrite)
	source, err := s.CreateNode(ctx, sourceScope, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "source", File: &InlineFile{Content: []byte("abc"), MediaType: "text/plain"}})
	require.NoError(t, err)
	in := CreateCopy{SourceID: source.ID, DestinationScopeID: destinationScope, ParentID: *scopes[1].RootID, Name: "copy", Revision: &source.Revision}
	_, err = s.AdmitCopy(ctx, sourceScope, uuid.New(), in)
	require.Equal(t, apperr.Forbidden, apperr.KindOf(err))
	testfixture.Grant(t, graph, "scope", destinationScope, actor, authz.ScopeWrite)
	_, err = s.GetNode(ctx, destinationScope, Locator{NodeID: &source.ID})
	require.Equal(t, apperr.Missing, apperr.KindOf(err))
	_, err = s.CreateNode(ctx, destinationScope, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "foreign"})
	require.Error(t, err)
	admission, err := s.AdmitCopy(ctx, sourceScope, uuid.New(), in)
	require.NoError(t, err)
	require.NoError(t, s.CopyTreeData(ctx, admission))
	copied, err := s.GetNode(ctx, destinationScope, Locator{NodeID: &admission.Root.Destination})
	require.NoError(t, err)
	require.Equal(t, destinationScope, copied.ScopeID)
	var used int64
	require.NoError(t, db.QueryRow(ctx, "SELECT used_bytes FROM filesystems WHERE id=$1", fs).Scan(&used))
	require.EqualValues(t, 6, used)
	_, err = s.CreateNode(ctx, sourceScope, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "over-quota", File: &InlineFile{Content: []byte("x"), MediaType: "text/plain"}})
	require.Equal(t, "QUOTA_EXCEEDED", reason(err))
}
