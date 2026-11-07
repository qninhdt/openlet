//go:build workflow

package temporal

import (
	"errors"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/stretchr/testify/mock"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/testsuite"
	"testing"
	"time"
)

func TestWorkspaceChangesSerializesAcrossActivityRetries(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var a *Activities
	id, actor := uuid.New(), uuid.New()
	first := Mutation{Kind: "member", WorkspaceID: id, ActorID: actor, TargetID: uuid.New(), Key: uuid.New()}
	second := Mutation{Kind: "member", WorkspaceID: id, ActorID: actor, TargetID: uuid.New(), Key: uuid.New()}
	// The next command cannot begin while the first graph write is retrying.
	env.OnActivity(a.UpdateMembership, mock.Anything, first).Return(workspace.Workspace{}, errors.New("graph response lost")).Once()
	applied := false
	env.OnActivity(a.UpdateMembership, mock.Anything, first).Run(func(mock.Arguments) { applied = true }).Return(workspace.Workspace{ID: id}, nil).Once()
	env.OnActivity(a.UpdateMembership, mock.Anything, second).Run(func(mock.Arguments) { require.True(t, applied) }).Return(workspace.Workspace{ID: id}, nil).Once()
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
	env.ExecuteWorkflow(WorkspaceChanges, id)
	require.Equal(t, 2, completed)
	require.Error(t, env.GetWorkflowError())
	env.AssertExpectations(t)
}
func TestWorkspaceChangesContinuesAfterDrainingUpdates(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	var a *Activities
	id := uuid.New()
	in := Mutation{Kind: "member", WorkspaceID: id, ActorID: uuid.New(), Key: uuid.New()}
	env.OnActivity(a.UpdateMembership, mock.Anything, in).Return(workspace.Workspace{ID: id}, nil).Times(100)
	completed := 0
	env.RegisterDelayedCallback(func() {
		for range 100 {
			env.UpdateWorkflow("mutate", uuid.NewString(), &testsuite.TestUpdateCallback{OnReject: func(err error) { require.NoError(t, err) }, OnComplete: func(_ any, err error) { require.NoError(t, err); completed++ }}, in)
		}
	}, time.Millisecond)
	env.ExecuteWorkflow(WorkspaceChanges, id)
	require.Equal(t, 100, completed)
	require.ErrorContains(t, env.GetWorkflowError(), "continue as new")
	env.AssertExpectations(t)
}
