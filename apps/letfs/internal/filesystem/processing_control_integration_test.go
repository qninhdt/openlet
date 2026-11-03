//go:build integration

package filesystem

import (
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

func TestIntegrationReprocessAdmissionReplayAndCurrentState(t *testing.T) {
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
	mounts := []Mount{{Path: "/drive", FilesystemID: fs}}
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeCreate, authz.ContentWrite, authz.ProcessingRead)
	file, err := s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: "report.pdf", File: &InlineFile{Content: []byte("pdf"), MediaType: "application/pdf"}})
	require.NoError(t, err)
	key := uuid.New()
	_, err = s.Reprocess(ctx, fs, mounts, file.ID, key)
	require.Equal(t, apperr.Forbidden, apperr.KindOf(err))
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.ProcessingRun)
	var wg sync.WaitGroup
	results, failures := make([]Reprocessing, 2), make([]error, 2)
	for i := range 2 {
		wg.Go(func() { results[i], failures[i] = s.Reprocess(ctx, fs, mounts, file.ID, key) })
	}
	wg.Wait()
	for _, failure := range failures {
		require.NoError(t, failure)
	}
	require.Equal(t, results[0], results[1])
	require.EqualValues(t, 2, results[0].Generation, "concurrent retries admit exactly one generation")
	require.Equal(t, (Generation{FileID: file.ID, Generation: 2}).WorkflowID(), results[0].WorkflowID)
	state, err := s.GetProcessing(ctx, fs, mounts, file.ID)
	require.NoError(t, err)
	require.EqualValues(t, 2, state.DesiredGeneration)
	require.Equal(t, "pending", state.PublicationStatus)
	candidate, err := s.PendingProcessing(t.Context(), file.ID)
	require.NoError(t, err)
	dispatch, err := s.ReconcileProcessing(t.Context(), candidate, false)
	require.NoError(t, err)
	require.True(t, dispatch, "missing workflow is eligible for dispatch")
	_, err = s.Reprocess(ctx, fs, mounts, file.ID, uuid.New())
	require.NoError(t, err)
	dispatch, err = s.ReconcileProcessing(t.Context(), candidate, true)
	require.NoError(t, err)
	require.False(t, dispatch, "an old observation cannot fail a later generation")
	candidate, err = s.PendingProcessing(t.Context(), file.ID)
	require.NoError(t, err)
	dispatch, err = s.ReconcileProcessing(t.Context(), candidate, true)
	require.NoError(t, err)
	require.False(t, dispatch)
	state, err = s.GetProcessing(ctx, fs, mounts, file.ID)
	require.NoError(t, err)
	require.Equal(t, "failed", state.PublicationStatus)
	require.Equal(t, "PROCESSING_FAILED", *state.ErrorCode)
	file, err = s.ReplaceContent(ctx, fs, mounts, Locator{NodeID: &file.ID}, &file.Revision, []byte("new pdf"), "application/pdf")
	require.NoError(t, err)
	_, err = s.Reprocess(ctx, fs, mounts, file.ID, key)
	require.Equal(t, "IDEMPOTENCY_CONFLICT", reason(err), "a receipt never refers to changed source bytes")
}
