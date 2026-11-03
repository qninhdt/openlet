//go:build workflow

package temporal

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/testsuite"
	"testing"
	"time"
)

func TestWorkspacePermissionsSerializesAcrossActivityRetries(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	preparations := 0
	env.SetOnLocalActivityStartedListener(func(info *activity.Info, _ context.Context, _ []any) {
		require.Equal(t, "PrepareMutation", info.ActivityType.Name)
		preparations++
	})
	var a *Activities
	id, actor := uuid.New(), uuid.New()
	first := Mutation{Kind: "member", WorkspaceID: id, ActorID: actor, TargetID: uuid.New(), Key: uuid.New()}
	second := Mutation{Kind: "member", WorkspaceID: id, ActorID: actor, TargetID: uuid.New(), Key: uuid.New()}
	preparedFirst, preparedSecond := PreparedMutation{Command: first}, PreparedMutation{Command: second}
	// The next command cannot begin while the first graph write is retrying.
	env.OnActivity(a.PrepareMutation, mock.Anything, first).Return(preparedFirst, nil).Once()
	env.OnActivity(a.ApplyMutation, mock.Anything, preparedFirst).Return(workspace.Workspace{}, errors.New("graph response lost")).Once()
	applied := false
	env.OnActivity(a.ApplyMutation, mock.Anything, preparedFirst).Run(func(mock.Arguments) { applied = true }).Return(workspace.Workspace{ID: id}, nil).Once()
	env.OnActivity(a.PrepareMutation, mock.Anything, second).Run(func(mock.Arguments) { require.True(t, applied) }).Return(preparedSecond, nil).Once()
	env.OnActivity(a.ApplyMutation, mock.Anything, preparedSecond).Return(workspace.Workspace{ID: id}, nil).Once()
	completed := 0
	env.RegisterDelayedCallback(func() {
		for _, in := range []Mutation{first, second} {
			env.UpdateWorkflow("mutate", in.Key.String(), &testsuite.TestUpdateCallback{
				OnReject: func(err error) { require.NoError(t, err) },
				OnComplete: func(_ any, err error) {
					require.NoError(t, err)
					completed++
					if completed == 2 {
						env.CancelWorkflow()
					}
				},
			}, in)
		}
	}, 0)
	env.ExecuteWorkflow(WorkspacePermissions, id)
	require.Equal(t, 2, completed)
	require.Equal(t, 2, preparations)
	require.Error(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
func TestWorkspacePermissionsContinuesAfterDrainingUpdates(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var a *Activities
	id := uuid.New()
	in := Mutation{Kind: "member", WorkspaceID: id, ActorID: uuid.New(), Key: uuid.New()}
	prepared := PreparedMutation{Command: in}
	env.OnActivity(a.PrepareMutation, mock.Anything, in).Return(prepared, nil).Times(100)
	env.OnActivity(a.ApplyMutation, mock.Anything, prepared).Return(workspace.Workspace{ID: id}, nil).Times(100)
	completed := 0
	env.RegisterDelayedCallback(func() {
		for range 100 {
			env.UpdateWorkflow("mutate", uuid.NewString(), &testsuite.TestUpdateCallback{OnReject: func(err error) { require.NoError(t, err) }, OnComplete: func(_ any, err error) { require.NoError(t, err); completed++ }}, in)
		}
	}, time.Millisecond)
	env.ExecuteWorkflow(WorkspacePermissions, id)
	require.Equal(t, 100, completed)
	require.ErrorContains(t, env.GetWorkflowError(), "continue as new")
	env.AssertExpectations(t)
}
func TestWorkspacePermissionsDeletionFailureStartsNoChild(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var a *Activities
	id, actor := uuid.New(), uuid.New()
	env.OnActivity(a.PrepareWorkspaceDeletion, mock.Anything, workspace.DeleteInput{ActorID: actor, WorkspaceID: id, Revision: "1"}).Return(workspace.Workspace{}, errors.New("graph unavailable")).Once()
	// Stop before a retry, proving no storage child starts before disabling access.
	env.RegisterDelayedCallback(func() {
		env.UpdateWorkflow("mutate", "delete", &testsuite.TestUpdateCallback{}, Mutation{Kind: "delete", WorkspaceID: id, ActorID: actor, Revision: "1"})
	}, 0)
	env.RegisterDelayedCallback(func() { env.CancelWorkflow() }, 500*time.Millisecond)
	env.ExecuteWorkflow(WorkspacePermissions, id)
	require.Error(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
