package temporal

import (
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
)

const CopyNodeName = "CopyNode"

type CopyStep struct {
	Admission filesystem.CopyAdmission `json:"admission"`
	Item      filesystem.CopyItem      `json:"item"`
}
type CopyNext struct {
	Admission filesystem.CopyAdmission `json:"admission"`
	Frame     filesystem.CopyFrame     `json:"frame"`
}

func copyErrorCode(err error) string {
	var application *temporal.ApplicationError
	if errors.As(err, &application) {
		return application.Type()
	}
	return "COPY_FAILED"
}
func CopyNode(ctx workflow.Context, state filesystem.CopyState) (filesystem.CopyState, error) {
	if err := workflow.SetQueryHandler(ctx, "progress", func() (filesystem.CopyState, error) { return state, nil }); err != nil {
		return filesystem.CopyState{}, err
	}
	short := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 3}})
	storage := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 150 * time.Second, HeartbeatTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 3}})
	for range 100 {
		if state.Status != "running" {
			break
		}
		var err error
		if state.Pending != nil {
			item := *state.Pending
			if state.CommittedNodes >= state.Admission.MaxNodes || item.Size > state.Admission.MaxBytes-state.CommittedBytes {
				state.Status = "failed"
				code := "RESOURCE_LIMIT"
				state.ErrorCode = &code
				break
			}
			err = workflow.ExecuteActivity(storage, "copy_item", CopyStep{Admission: state.Admission, Item: item}).Get(storage, nil)
			if err == nil {
				state.CommittedNodes++
				state.CommittedBytes += item.Size
				state.Pending = nil
				if len(state.Frames) > 0 {
					parent := &state.Frames[len(state.Frames)-1]
					parent.After = item.Source
					parent.Revision = item.ParentRevision + 1
				}
				state.Frames = append(state.Frames, filesystem.CopyFrame{Item: item, After: uuid.Nil, Revision: 1})
			}
		} else if len(state.Frames) > 0 {
			frame := state.Frames[len(state.Frames)-1]
			input := CopyNext{Admission: state.Admission, Frame: frame}
			var item *filesystem.CopyItem
			err = workflow.ExecuteActivity(short, "next_copy_item", input).Get(short, &item)
			if err == nil {
				if item != nil {
					state.Pending = item
				} else {
					if frame.Item.Kind == "file" && !frame.Item.Derived {
						err = workflow.ExecuteActivity(short, "finish_copy_file", input).Get(short, nil)
					}
					if err == nil {
						state.Frames = state.Frames[:len(state.Frames)-1]
					}
				}
			}
		} else {
			state.Status = "succeeded"
		}
		if err != nil {
			state.Status = "failed"
			code := copyErrorCode(err)
			state.ErrorCode = &code
		}
	}
	if state.Status == "running" {
		return filesystem.CopyState{}, workflow.NewContinueAsNewError(ctx, CopyNodeName, state)
	}
	err := workflow.ExecuteActivity(short, "complete_copy", state.Admission).Get(short, nil)
	return state, err
}
