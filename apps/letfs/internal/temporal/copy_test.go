//go:build workflow

package temporal

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"
	"openlet/apps/letfs/internal/filesystem"
)

func copyInput() CopyState {
	return NewCopyState(filesystem.CopyAdmission{
		ID: uuid.New(), FilesystemID: uuid.New(), ActorID: uuid.New(),
		Root:     filesystem.CopyItem{Source: uuid.New(), Destination: uuid.New(), Kind: "directory", ParentRevision: 4},
		MaxNodes: 1000, MaxBytes: 1000, Deadline: time.Now().UTC().Add(time.Hour),
	})
}

func TestCopyNodeKeepsPartialProgressAndBusinessFailure(t *testing.T) {
	for _, fail := range []bool{false, true} {
		t.Run(map[bool]string{false: "success", true: "source changed"}[fail], func(t *testing.T) {
			var suite testsuite.WorkflowTestSuite
			env := suite.NewTestWorkflowEnvironment()
			input := copyInput()
			child := filesystem.CopyItem{Source: uuid.New(), Destination: uuid.New(), Parent: input.Admission.Root.Destination,
				Kind: "file", Size: 7, ParentRevision: 1}
			var calls []string
			env.RegisterActivityWithOptions(func(ctx context.Context, step CopyStep) error {
				require.Equal(t, input.Admission, step.Admission)
				require.Equal(t, 30*time.Second, activity.GetInfo(ctx).HeartbeatTimeout)
				calls = append(calls, "copy "+step.Item.Kind)
				if fail && step.Item.Source == child.Source {
					return temporal.NewNonRetryableApplicationError("source changed", "SOURCE_REPLACED", nil)
				}
				return nil
			}, activity.RegisterOptions{Name: "copy_item"})
			env.RegisterActivityWithOptions(func(_ context.Context, next CopyNext) (*filesystem.CopyItem, error) {
				calls = append(calls, "next "+next.Frame.Item.Kind)
				if next.Frame.Item.Source == input.Admission.Root.Source && next.Frame.After == uuid.Nil {
					return &child, nil
				}
				if next.Frame.Item.Source == input.Admission.Root.Source {
					require.Equal(t, child.Source, next.Frame.After)
					require.EqualValues(t, 2, next.Frame.Revision)
				}
				return nil, nil
			}, activity.RegisterOptions{Name: "next_copy_item"})
			env.RegisterActivityWithOptions(func(_ context.Context, next CopyNext) error {
				calls = append(calls, "finish "+next.Frame.Item.Kind)
				return nil
			}, activity.RegisterOptions{Name: "finish_copy_file"})
			env.RegisterActivityWithOptions(func(_ context.Context, admission filesystem.CopyAdmission) error {
				require.Equal(t, input.Admission, admission)
				calls = append(calls, "complete")
				return nil
			}, activity.RegisterOptions{Name: "complete_copy"})
			env.ExecuteWorkflow(CopyNode, input)
			require.NoError(t, env.GetWorkflowError())
			var result CopyState
			require.NoError(t, env.GetWorkflowResult(&result))
			progress, err := env.QueryWorkflow("progress")
			require.NoError(t, err)
			var queried CopyState
			require.NoError(t, progress.Get(&queried))
			require.Equal(t, result, queried)
			if fail {
				require.Equal(t, []string{"copy directory", "next directory", "copy file", "complete"}, calls)
				require.Equal(t, "failed", result.Status)
				require.Equal(t, "SOURCE_REPLACED", *result.ErrorCode)
				require.EqualValues(t, 1, result.CommittedNodes)
				require.Zero(t, result.CommittedBytes)
				require.Equal(t, &child, result.Pending)
			} else {
				require.Equal(t, []string{"copy directory", "next directory", "copy file", "next file", "finish file", "next directory", "finish directory", "complete"}, calls)
				require.Equal(t, "succeeded", result.Status)
				require.Nil(t, result.ErrorCode)
				require.EqualValues(t, 2, result.CommittedNodes)
				require.EqualValues(t, 7, result.CommittedBytes)
				require.Empty(t, result.Frames)
				require.Nil(t, result.Pending)
			}
		})
	}
}

func TestCopyNodeRejectsBudgetBeforeIO(t *testing.T) {
	for _, nodes := range []bool{true, false} {
		var suite testsuite.WorkflowTestSuite
		env := suite.NewTestWorkflowEnvironment()
		input := copyInput()
		if nodes {
			input.CommittedNodes = input.Admission.MaxNodes
		} else {
			input.CommittedBytes = input.Admission.MaxBytes
			input.Pending.Size = 1
		}
		env.RegisterActivityWithOptions(func(context.Context, filesystem.CopyAdmission) error { return nil }, activity.RegisterOptions{Name: "complete_copy"})
		env.ExecuteWorkflow(CopyNode, input)
		require.NoError(t, env.GetWorkflowError())
		var result CopyState
		require.NoError(t, env.GetWorkflowResult(&result))
		require.Equal(t, "failed", result.Status)
		require.Equal(t, "RESOURCE_LIMIT", *result.ErrorCode)
		require.Equal(t, input.Pending, result.Pending)
	}
}

func TestCopyNodeContinuesWithBoundedTraversalState(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	input := copyInput()
	var commits int
	env.RegisterActivityWithOptions(func(context.Context, CopyStep) error { commits++; return nil }, activity.RegisterOptions{Name: "copy_item"})
	env.RegisterActivityWithOptions(func(_ context.Context, next CopyNext) (*filesystem.CopyItem, error) {
		return &filesystem.CopyItem{Source: uuid.New(), Destination: uuid.New(), Parent: next.Frame.Item.Destination,
			ParentRevision: next.Frame.Revision, Kind: "directory", Size: 2}, nil
	}, activity.RegisterOptions{Name: "next_copy_item"})
	env.ExecuteWorkflow(CopyNode, input)
	var continued *workflow.ContinueAsNewError
	require.True(t, errors.As(env.GetWorkflowError(), &continued))
	require.Equal(t, CopyNodeName, continued.WorkflowType.Name)
	var state CopyState
	require.NoError(t, converter.GetDefaultDataConverter().FromPayloads(continued.Input, &state))
	require.Equal(t, input.Admission, state.Admission)
	require.Equal(t, "running", state.Status)
	require.Equal(t, 50, commits)
	require.EqualValues(t, 50, state.CommittedNodes)
	require.EqualValues(t, 98, state.CommittedBytes)
	require.Len(t, state.Frames, 50)
	require.NotNil(t, state.Pending)
	require.Equal(t, state.Frames[49].Item.Destination, state.Pending.Parent)
	require.EqualValues(t, 1, state.Pending.ParentRevision)
}

func TestCopyNodeRetriesTransientActivityOnly(t *testing.T) {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	input := copyInput()
	var attempts []int32
	env.RegisterActivityWithOptions(func(ctx context.Context, _ CopyStep) error {
		attempts = append(attempts, activity.GetInfo(ctx).Attempt)
		return temporal.NewApplicationError("unavailable", "DEPENDENCY_UNAVAILABLE")
	}, activity.RegisterOptions{Name: "copy_item"})
	env.RegisterActivityWithOptions(func(context.Context, filesystem.CopyAdmission) error { return nil }, activity.RegisterOptions{Name: "complete_copy"})
	env.ExecuteWorkflow(CopyNode, input)
	require.NoError(t, env.GetWorkflowError())
	var result CopyState
	require.NoError(t, env.GetWorkflowResult(&result))
	require.Equal(t, []int32{1, 2, 3}, attempts)
	require.Equal(t, "DEPENDENCY_UNAVAILABLE", *result.ErrorCode)
	require.Zero(t, result.CommittedNodes)
}
