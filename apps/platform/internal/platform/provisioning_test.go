package platform

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
)

func TestDeleteWorkspaceObservesBothOwners(t *testing.T) {
	for _, storageFails := range []bool{false, true} {
		t.Run(map[bool]string{false: "storage completes before agent cleanup", true: "storage failure preserves record"}[storageFails], func(t *testing.T) {
			var suite testsuite.WorkflowTestSuite
			env := suite.NewTestWorkflowEnvironment()
			noop := func(context.Context, sdk.WorkspaceCleanup) error { return nil }
			for _, name := range []string{"RevokeWorkspaceAccess", "DeleteWorkspaceStorage", "DeleteWorkspaceAgents", "DeleteWorkspaceRecord"} {
				env.RegisterActivityWithOptions(noop, activity.RegisterOptions{Name: name})
			}
			payload := sdk.WorkspaceCleanup{WorkspaceID: "a259f79c-6945-4f28-838a-8699852122f6"}
			raw, err := json.Marshal(payload)
			require.NoError(t, err)
			require.JSONEq(t, `{"workspace_id":"a259f79c-6945-4f28-838a-8699852122f6"}`, string(raw))
			env.OnActivity("RevokeWorkspaceAccess", mock.Anything, payload).Return(nil).Once()
			var storageErr error
			if storageFails {
				storageErr = temporal.NewNonRetryableApplicationError("storage unavailable", "storage", nil)
			}
			env.OnActivity("DeleteWorkspaceStorage", mock.Anything, payload).Return(storageErr).Once()
			env.OnActivity("DeleteWorkspaceAgents", mock.Anything, payload).After(time.Minute).Return(nil).Once()
			deleted := false
			if !storageFails {
				env.OnActivity("DeleteWorkspaceRecord", mock.Anything, payload).Return(func(context.Context, sdk.WorkspaceCleanup) error { deleted = true; return nil }).Once()
			} else {
				env.OnActivity("DeleteWorkspaceRecord", mock.Anything, payload).Never()
			}
			env.RegisterDelayedCallback(func() { require.Equal(t, !storageFails, deleted) }, 30*time.Second)
			env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkspaceInput{WorkspaceID: payload.WorkspaceID, LetFSQueue: "storage", LetaBridgeQueue: "agents"})
			require.True(t, env.IsWorkflowCompleted())
			if storageFails {
				require.Error(t, env.GetWorkflowError())
			} else {
				require.NoError(t, env.GetWorkflowError())
			}
			env.AssertExpectations(t)
		})
	}
}
