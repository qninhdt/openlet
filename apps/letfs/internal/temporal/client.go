package temporal

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"google.golang.org/grpc/codes"
	"openlet/apps/letfs/internal/filesystem"
	"openlet/packages/go/rpc"
)

type Jobs struct{ Client client.Client }

func dependencyError(err error) error {
	if err == nil {
		return nil
	}
	return rpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "Temporal unavailable")
}

func copyWorkflowID(fs, id uuid.UUID) string { return "copy/" + fs.String() + "/" + id.String() }

func (j *Jobs) StartCopy(ctx context.Context, admission filesystem.CopyAdmission) error {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	_, err := j.Client.ExecuteWorkflow(ctx, client.StartWorkflowOptions{
		ID: copyWorkflowID(admission.FilesystemID, admission.ID), TaskQueue: Queue,
		WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING,
		WorkflowIDReusePolicy:    enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE,
		WorkflowExecutionTimeout: time.Hour,
	}, CopyNodeName, NewCopyState(admission))
	return dependencyError(err)
}

func (j *Jobs) Copy(ctx context.Context, fs, id, actor uuid.UUID, inspectAny bool) (CopyState, error) {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	workflowID := copyWorkflowID(fs, id)
	info, err := j.Client.DescribeWorkflowExecution(ctx, workflowID, "")
	var missing *serviceerror.NotFound
	if errors.As(err, &missing) {
		return CopyState{}, rpc.Fault(codes.NotFound, "COPY_EXPIRED", "copy history unavailable")
	}
	if err != nil {
		return CopyState{}, dependencyError(err)
	}
	runID := info.WorkflowExecutionInfo.Execution.RunId
	history := j.Client.GetWorkflowHistory(ctx, workflowID, runID, false, enums.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
	event, err := history.Next()
	if err != nil {
		return CopyState{}, dependencyError(err)
	}
	started := event.GetWorkflowExecutionStartedEventAttributes()
	var initial CopyState
	if started == nil || converter.GetDefaultDataConverter().FromPayloads(started.Input, &initial) != nil ||
		initial.Admission.FilesystemID != fs || initial.Admission.ID != id || initial.Admission.ActorID != actor && !inspectAny {
		return CopyState{}, rpc.Fault(codes.NotFound, "NOT_FOUND", "copy not found")
	}
	var result CopyState
	if info.WorkflowExecutionInfo.Status == enums.WORKFLOW_EXECUTION_STATUS_COMPLETED {
		err = j.Client.GetWorkflow(ctx, workflowID, runID).Get(ctx, &result)
	} else {
		var encoded converter.EncodedValue
		encoded, err = j.Client.QueryWorkflow(ctx, workflowID, runID, "progress")
		if err == nil {
			err = encoded.Get(&result)
		}
	}
	if err != nil {
		return CopyState{}, dependencyError(err)
	}
	switch info.WorkflowExecutionInfo.Status {
	case enums.WORKFLOW_EXECUTION_STATUS_FAILED, enums.WORKFLOW_EXECUTION_STATUS_CANCELED,
		enums.WORKFLOW_EXECUTION_STATUS_TERMINATED, enums.WORKFLOW_EXECUTION_STATUS_TIMED_OUT:
		result.Status = "failed"
		code := "COPY_FAILED"
		result.ErrorCode = &code
	}
	return result, nil
}

func (j *Jobs) StartDeletion(ctx context.Context, input DeletionInput) error {
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	name := DeleteFilesystemName
	if input.EntryID != nil {
		name = PurgeTrashName
	}
	_, err := j.Client.ExecuteWorkflow(ctx, client.StartWorkflowOptions{
		ID: input.WorkflowID(), TaskQueue: Queue,
		WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING,
		WorkflowIDReusePolicy:    enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE,
		WorkflowExecutionTimeout: 7 * 24 * time.Hour,
	}, name, input)
	return dependencyError(err)
}
