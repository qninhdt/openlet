package temporal

import (
	"context"
	"errors"
	"time"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/client"
)

// WorkflowStatus returns nil when no run exists at or after the observed admission.
func (j *Jobs) WorkflowStatus(ctx context.Context, id string, since *time.Time) (*bool, error) {
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	response, err := j.Client.DescribeWorkflowExecution(ctx, id, "")
	var missing *serviceerror.NotFound
	if errors.As(err, &missing) {
		return nil, nil
	}
	if err != nil {
		return nil, dependencyError(err)
	}
	info := response.GetWorkflowExecutionInfo()
	if info == nil || info.Status == enums.WORKFLOW_EXECUTION_STATUS_UNSPECIFIED {
		return nil, dependencyError(errors.New("workflow status missing"))
	}
	running := info.Status == enums.WORKFLOW_EXECUTION_STATUS_RUNNING
	if !running {
		if info.CloseTime == nil || info.CloseTime.CheckValid() != nil {
			return nil, dependencyError(errors.New("workflow close time missing"))
		}
		if since != nil && info.CloseTime.AsTime().Before(*since) {
			return nil, nil
		}
	}
	return &running, nil
}

func (j *Jobs) StartProcessing(ctx context.Context, dispatch filesystem.ProcessingDispatch) error {
	if dispatch.Publication != "pending" && dispatch.Publication != "parsed" && dispatch.Publication != "enriched" {
		return nil
	}
	id := dispatch.Source.WorkflowID()
	reuse := enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE
	if dispatch.Publication == "enriched" {
		reuse = enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	_, err := j.Client.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: id, TaskQueue: Queue,
		WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: reuse,
		WorkflowExecutionTimeout: 22500 * time.Second,
	}, ProcessFileName, ProcessFileInput{Source: dispatch.Source, ParseRequired: dispatch.Publication == "pending", EnrichmentRequired: dispatch.Publication != "enriched"})
	var duplicate *serviceerror.WorkflowExecutionAlreadyStarted
	if errors.As(err, &duplicate) {
		return nil
	}
	return dependencyError(err)
}
