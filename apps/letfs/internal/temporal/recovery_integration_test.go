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
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"go.temporal.io/api/enums/v1"
	historypb "go.temporal.io/api/history/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"

	"google.golang.org/protobuf/encoding/protojson"
)

func replayRuns(t *testing.T, tc client.Client, id, runID, name string) int {
	t.Helper()
	replayer := worker.NewWorkflowReplayer()
	replayer.RegisterWorkflowWithOptions(DeleteScope, workflow.RegisterOptions{Name: DeleteScopeName})
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

func TestIntegrationFilesystemDeletionWorkerRestart(t *testing.T) {
	tc, _ := sharedfixture.Temporal(t)
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	store := &filesystem.Store{DB: db, Graph: graph, MaxNodes: 1000, MaxCopyNodes: 100, InlineLimit: 64, MaxFileBytes: 64, MaxOutstanding: 100, MaxCleanupBacklog: 100}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx, cancel := context.WithTimeout(identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, Service: "gateway", Gateway: true, ActorID: actor}), 2*time.Minute)
	defer cancel()
	fs, scope := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: fs, LimitBytes: 3})
	require.NoError(t, err)
	created, err := createTestScope(owner, store, uuid.New(), fs, scope)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", scope, actor, authz.ScopeManageAccess)
	source, err := store.CreateNode(ctx, scope, uuid.New(), filesystem.CreateNode{Parent: filesystem.Locator{NodeID: created.RootID}, Name: "source"})
	require.NoError(t, err)
	for _, name := range []string{"a", "b"} {
		_, err = store.CreateNode(ctx, scope, uuid.New(), filesystem.CreateNode{Parent: filesystem.Locator{NodeID: &source.ID}, Name: name, File: &filesystem.InlineFile{Content: []byte("x"), MediaType: "text/plain"}})
		require.NoError(t, err)
	}
	source, err = store.GetNode(ctx, scope, filesystem.Locator{NodeID: &source.ID})
	require.NoError(t, err)
	activities := &Activities{Store: store}
	first := worker.New(tc, Queue, worker.Options{WorkerStopTimeout: time.Second})
	Register(first, activities)
	require.NoError(t, first.Start())
	stopped := false
	t.Cleanup(func() {
		if !stopped {
			first.Stop()
		}
	})
	var used, nodes int64
	_, err = db.Exec(ctx, "UPDATE filesystems SET limit_bytes=1000 WHERE id=$1", fs)
	require.NoError(t, err)
	for i := range 70 {
		_, err = store.CreateNode(ctx, scope, uuid.New(), filesystem.CreateNode{Parent: filesystem.Locator{NodeID: created.RootID}, Name: fmt.Sprintf("batch-%02d", i), File: &filesystem.InlineFile{Content: []byte("x"), MediaType: "text/plain"}})
		require.NoError(t, err)
	}
	// Pause the real bulk activity's second SQL batch after its first commit.
	_, err = db.Exec(ctx, fmt.Sprintf(`CREATE FUNCTION pause_later_batches() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN IF (SELECT count(*) FROM nodes WHERE scope_id='%s')<=64 THEN PERFORM pg_advisory_xact_lock(7421); END IF; RETURN NULL; END $$;
 CREATE TRIGGER pause_later_batches BEFORE DELETE ON nodes FOR EACH STATEMENT EXECUTE FUNCTION pause_later_batches()`, scope))
	require.NoError(t, err)
	lock, err := db.Begin(ctx)
	require.NoError(t, err)
	defer lock.Rollback(context.Background())
	_, err = lock.Exec(ctx, "SELECT pg_advisory_xact_lock(7421)")
	require.NoError(t, err)
	deletion, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{TaskQueue: Queue}, DeleteFilesystemName, shared.FilesystemDeletion{FilesystemID: fs})
	require.NoError(t, err)
	require.Eventually(t, func() bool {
		err := db.QueryRow(ctx, "SELECT used_bytes,node_count FROM filesystems WHERE id=$1", fs).Scan(&used, &nodes)
		return err == nil && nodes == 10 && used == 8
	}, 10*time.Second, 10*time.Millisecond)
	first.Stop()
	stopped = true
	require.NoError(t, lock.Rollback(ctx))
	duplicate, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{TaskQueue: Queue}, DeleteScopeName, shared.ScopeDeletion{FilesystemID: fs, ScopeID: scope})
	require.NoError(t, err)
	second := worker.New(tc, Queue, worker.Options{WorkerStopTimeout: time.Second})
	Register(second, activities)
	require.NoError(t, second.Start())
	t.Cleanup(second.Stop)
	require.NoError(t, deletion.Get(ctx, nil))
	require.NoError(t, duplicate.Get(ctx, nil))
	require.Equal(t, 1, replayRuns(t, tc, duplicate.GetID(), duplicate.GetRunID(), "DeleteScope"))
	require.Equal(t, 1, replayRuns(t, tc, deletion.GetID(), deletion.GetRunID(), "DeleteFilesystem"))
	var state string
	require.NoError(t, db.QueryRow(ctx, "SELECT state,used_bytes,node_count FROM filesystems WHERE id=$1", fs).Scan(&state, &used, &nodes))
	require.Equal(t, "deleted", state)
	require.Zero(t, used)
	require.Zero(t, nodes)
}
