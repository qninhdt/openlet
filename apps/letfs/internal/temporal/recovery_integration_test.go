//go:build integration

package temporal

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"go.temporal.io/api/enums/v1"
	historypb "go.temporal.io/api/history/v1"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	sdktemporal "go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/encoding/protojson"
	"openlet/apps/letfs/internal/filesystem"
	"openlet/apps/letfs/internal/testfixture"
	"openlet/packages/go/authz"
	"openlet/packages/go/identity"
	sharedfixture "openlet/packages/go/testfixture"
)

func replayRuns(t *testing.T, tc client.Client, id, runID, name string) int {
	t.Helper()
	replayer := worker.NewWorkflowReplayer()
	replayer.RegisterWorkflowWithOptions(CopyNode, workflow.RegisterOptions{Name: CopyNodeName})
	replayer.RegisterWorkflowWithOptions(PurgeTrash, workflow.RegisterOptions{Name: PurgeTrashName})
	replayer.RegisterWorkflowWithOptions(DeleteFilesystem, workflow.RegisterOptions{Name: DeleteFilesystemName})
	replayer.RegisterWorkflowWithOptions(ProcessFile, workflow.RegisterOptions{Name: ProcessFileName})
	replayer.RegisterWorkflowWithOptions(StorageMaintenance, workflow.RegisterOptions{Name: StorageMaintenanceName})
	runs := 0
	for runID != "" {
		ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
		history := &historypb.History{}
		iterator := tc.GetWorkflowHistory(ctx, id, runID, false, enums.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
		next := ""
		for iterator.HasNext() {
			event, err := iterator.Next()
			require.NoError(t, err)
			history.Events = append(history.Events, event)
			if continued := event.GetWorkflowExecutionContinuedAsNewEventAttributes(); continued != nil {
				next = continued.NewExecutionRunId
			}
		}
		cancel()
		require.NoError(t, replayer.ReplayWorkflowHistory(nil, history))
		if dir := os.Getenv("OPENLET_HISTORY_DIR"); dir != "" {
			require.NoError(t, os.MkdirAll(dir, 0o700))
			data, err := protojson.MarshalOptions{Indent: "  "}.Marshal(history)
			require.NoError(t, err)
			require.NoError(t, os.WriteFile(filepath.Join(dir, fmt.Sprintf("%s-%d.json", name, runs)), data, 0o600))
		}
		runs++
		runID = next
	}
	return runs
}

func TestIntegrationCopyRecoveryContinuationAndDeletionReplay(t *testing.T) {
	tc, _ := testfixture.Temporal(t)
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := &filesystem.Store{DB: db, Graph: graph, MaxNodes: 1000, MaxCopyNodes: 1000, InlineLimit: 64, MaxFileBytes: 64,
		MaxOutstanding: 100, MaxCleanupBacklog: 100}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	bucket, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateBucket(owner, uuid.New(), filesystem.CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	root := *created.RootID
	mounts := []filesystem.Mount{{Path: "/drive", FilesystemID: fs}}
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeCreate, authz.NodeRead, authz.NodeTrash,
		authz.CopyCreate, authz.CopyRead, authz.TrashPurge)
	source, err := s.CreateNode(ctx, fs, mounts, uuid.New(), filesystem.CreateNode{Parent: filesystem.Locator{NodeID: &root}, Name: "source"})
	require.NoError(t, err)
	for i := range 40 {
		_, err = s.CreateNode(ctx, fs, mounts, uuid.New(), filesystem.CreateNode{Parent: filesystem.Locator{NodeID: &source.ID},
			Name: fmt.Sprintf("%02d.bin", i), File: &filesystem.InlineFile{Content: []byte{byte(i)}, MediaType: "application/octet-stream"}})
		require.NoError(t, err)
	}
	source, err = s.GetNode(ctx, fs, mounts, filesystem.Locator{NodeID: &source.ID})
	require.NoError(t, err)
	admission, err := s.AdmitCopy(ctx, fs, mounts, uuid.New(), filesystem.CreateCopy{SourceID: source.ID, ParentID: root, Name: "copy", Revision: &source.Revision})
	require.NoError(t, err)
	a := &Activities{Store: s}
	first := worker.New(tc, Queue, worker.Options{WorkerStopTimeout: time.Second})
	Register(first, a)
	committed := make(chan struct{})
	first.RegisterActivityWithOptions(func(ctx context.Context, step CopyStep) error {
		if err := a.CopyItem(ctx, step); err != nil {
			return err
		}
		if step.Item.Source == source.ID && activity.GetInfo(ctx).Attempt == 1 {
			close(committed)
			return sdktemporal.NewApplicationError("lost acknowledgment", "DEPENDENCY_UNAVAILABLE")
		}
		return nil
	}, activity.RegisterOptions{Name: "copy_item", DisableAlreadyRegisteredCheck: true})
	require.NoError(t, first.Start())
	firstStopped := false
	t.Cleanup(func() {
		if !firstStopped {
			first.Stop()
		}
	})
	jobs := &Jobs{Client: tc}
	require.NoError(t, jobs.StartCopy(ctx, admission))
	initial, err := tc.DescribeWorkflowExecution(ctx, copyWorkflowID(fs, admission.ID), "")
	require.NoError(t, err)
	select {
	case <-committed:
	case <-time.After(20 * time.Second):
		t.Fatal("copy did not reach committed-before-acknowledgment boundary")
	}
	first.Stop()
	firstStopped = true
	second := worker.New(tc, Queue, worker.Options{WorkerStopTimeout: time.Second})
	Register(second, a)
	require.NoError(t, second.Start())
	secondStopped := false
	t.Cleanup(func() {
		if !secondStopped {
			second.Stop()
		}
	})
	deadline, cancel := context.WithTimeout(ctx, time.Minute)
	defer cancel()
	var result CopyState
	require.NoError(t, tc.GetWorkflow(deadline, copyWorkflowID(fs, admission.ID), "").Get(deadline, &result))
	require.Equal(t, "succeeded", result.Status)
	require.EqualValues(t, 41, result.CommittedNodes)
	require.EqualValues(t, 40, result.CommittedBytes)
	var bytes, nodes int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&bytes))
	require.EqualValues(t, 80, bytes)
	require.NoError(t, db.QueryRow(ctx, `SELECT node_count FROM filesystems WHERE id=$1`, fs).Scan(&nodes))
	require.EqualValues(t, 83, nodes)
	require.GreaterOrEqual(t, replayRuns(t, tc, copyWorkflowID(fs, admission.ID), initial.WorkflowExecutionInfo.Execution.RunId, "CopyNodeRecovery"), 2)
	// A completed receipt must not start another execution or charge quota again.
	require.NoError(t, jobs.StartCopy(ctx, admission))
	second.Stop()
	secondStopped = true
	progress, err := jobs.Copy(ctx, fs, admission.ID, actor, false)
	require.NoError(t, err, "completed progress does not need a running worker")
	require.Equal(t, "succeeded", progress.Status)
	_, err = jobs.Copy(ctx, fs, admission.ID, uuid.New(), false)
	require.Equal(t, codes.NotFound, status.Code(err))
	_, err = jobs.Copy(ctx, fs, admission.ID, uuid.New(), true)
	require.NoError(t, err)
	copy, err := s.GetNode(ctx, fs, mounts, filesystem.Locator{NodeID: &admission.Root.Destination})
	require.NoError(t, err)
	entry, err := s.TrashNode(ctx, fs, mounts, filesystem.Locator{NodeID: &copy.ID}, &copy.Revision)
	require.NoError(t, err)
	_, err = s.PrepareTrashPurge(ctx, fs, entry.ID)
	require.NoError(t, err)
	purge := DeletionInput{FilesystemID: fs, EntryID: &entry.ID}
	require.NoError(t, jobs.StartDeletion(ctx, purge))
	require.NoError(t, tc.CancelWorkflow(ctx, purge.WorkflowID(), ""))
	third := worker.New(tc, Queue, worker.Options{WorkerStopTimeout: time.Second})
	Register(third, a)
	require.NoError(t, third.Start())
	t.Cleanup(third.Stop)
	var purged uuid.UUID
	require.NoError(t, tc.GetWorkflow(deadline, purge.WorkflowID(), "").Get(deadline, &purged))
	require.Equal(t, entry.ID, purged)
	info, err := tc.DescribeWorkflowExecution(ctx, purge.WorkflowID(), "")
	require.NoError(t, err)
	require.Equal(t, 1, replayRuns(t, tc, purge.WorkflowID(), info.WorkflowExecutionInfo.Execution.RunId, "PurgeTrashCanceled"))
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&bytes))
	require.EqualValues(t, 40, bytes)
	require.NoError(t, s.PrepareFilesystemDeletion(owner, fs))
	deletion := DeletionInput{FilesystemID: fs}
	require.NoError(t, jobs.StartDeletion(ctx, deletion))
	var deleted uuid.UUID
	require.NoError(t, tc.GetWorkflow(deadline, deletion.WorkflowID(), "").Get(deadline, &deleted))
	require.Equal(t, fs, deleted)
	info, err = tc.DescribeWorkflowExecution(ctx, deletion.WorkflowID(), "")
	require.NoError(t, err)
	require.Equal(t, 1, replayRuns(t, tc, deletion.WorkflowID(), info.WorkflowExecutionInfo.Execution.RunId, "DeleteFilesystem"))
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&bytes))
	require.Zero(t, bytes)
	var state string
	require.NoError(t, db.QueryRow(ctx, `SELECT state,node_count FROM filesystems WHERE id=$1`, fs).Scan(&state, &nodes))
	require.Equal(t, "deleted", state)
	require.Zero(t, nodes)
}
