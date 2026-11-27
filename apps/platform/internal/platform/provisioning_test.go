package platform

import (
	"context"
	"encoding/json"
	"testing"
	"time"

	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/platform/v1"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/types/known/emptypb"
)

func TestProvisionWorkspaceReturnsFinalStorageRevision(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	env.RegisterActivityWithOptions(func(context.Context, ProvisionInput) (*ProvisionResult, error) { return nil, nil }, activity.RegisterOptions{Name: "AdmitWorkspace"})
	env.RegisterActivityWithOptions(func(context.Context, ProvisionInput) (string, error) { return "", nil }, activity.RegisterOptions{Name: "ProvisionWorkspaceAccess"})
	env.RegisterActivityWithOptions(func(context.Context, sdk.InitialStoragesInput) (string, error) { return "", nil }, activity.RegisterOptions{Name: "ProvisionInitialStorages"})
	env.RegisterActivityWithOptions(func(context.Context, string) (*pb.Workspace, error) { return nil, nil }, activity.RegisterOptions{Name: "ActivateWorkspace"})
	in := ProvisionInput{WorkspaceID: "workspace", LetFSQueue: "letfs"}
	env.OnActivity("AdmitWorkspace", mock.Anything, in).Return(&ProvisionResult{}, nil).Once()
	env.OnActivity("ProvisionWorkspaceAccess", mock.Anything, in).Return("membership-revision", nil).Once()
	env.OnActivity("ProvisionInitialStorages", mock.Anything, sdk.InitialStoragesInput{WorkspaceID: in.WorkspaceID, ZedToken: "membership-revision"}).Return("storage-revision", nil).Once()
	env.OnActivity("ActivateWorkspace", mock.Anything, in.WorkspaceID).Return(&pb.Workspace{Id: in.WorkspaceID}, nil).Once()
	env.ExecuteWorkflow(ProvisionWorkspace, in)
	require.NoError(t, env.GetWorkflowError())
	var result ProvisionResult
	require.NoError(t, env.GetWorkflowResult(&result))
	require.Equal(t, "storage-revision", result.ZedToken)
	env.AssertExpectations(t)
}

func TestDeleteWorkspaceObservesAllOwners(t *testing.T) {
	for _, storageFails := range []bool{false, true} {
		t.Run(map[bool]string{false: "all owners complete before record delete", true: "storage failure preserves record"}[storageFails], func(t *testing.T) {
			var suite testsuite.WorkflowTestSuite
			env := suite.NewTestWorkflowEnvironment()
			noop := func(context.Context, sdk.WorkspaceCleanup) error { return nil }
			for _, name := range []string{"RevokeWorkspaceAccess", "DeleteWorkspaceStorage", "DeleteWorkspaceChat", "DeleteWorkspaceAgents", "DeleteWorkspaceRecord"} {
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
			env.OnActivity("DeleteWorkspaceChat", mock.Anything, payload).Return(nil).Once()
			env.OnActivity("DeleteWorkspaceAgents", mock.Anything, payload).After(time.Minute).Return(nil).Once()
			if !storageFails {
				env.OnActivity("DeleteWorkspaceRecord", mock.Anything, payload).Return(nil).Once()
			} else {
				env.OnActivity("DeleteWorkspaceRecord", mock.Anything, payload).Never()
			}
			env.ExecuteWorkflow(DeleteWorkspace, DeleteWorkspaceInput{WorkspaceID: payload.WorkspaceID, LetFSQueue: "storage"})
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

func TestGetRealtimeConnectToken(t *testing.T) {
	s := &Server{CentrifugoSecret: "super-secret", CentrifugoTTL: 30 * time.Minute}
	uid := "a259f79c-6945-4f28-838a-8699852122f6"
	ctx := metadata.NewIncomingContext(context.Background(), metadata.Pairs("x-openlet-user-id", uid))
	resp, err := s.GetRealtimeConnectToken(ctx, &emptypb.Empty{})
	require.NoError(t, err)
	require.Equal(t, uid, resp.UserId)
	require.NotEmpty(t, resp.Token)
	require.True(t, resp.ExpiresAt.AsTime().After(time.Now().Add(20*time.Minute)))
}
