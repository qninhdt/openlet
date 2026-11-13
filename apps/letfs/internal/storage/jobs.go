package storage

import (
	"context"
	"errors"
	"fmt"
	"time"

	"go.temporal.io/api/serviceerror"

	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

type ProcessInput struct {
	FileID               string `json:"file_id"`
	Version              int64  `json:"version"`
	ParseRequired        bool   `json:"parse_required"`
	CPUQueue             string `json:"cpu_queue"`
	IOQueue              string `json:"io_queue"`
	ParseTimeoutSeconds  int    `json:"parse_timeout_seconds"`
	EnrichTimeoutSeconds int    `json:"enrich_timeout_seconds"`
}

func RegisterWorker(w worker.Worker, s *Server) {
	w.RegisterWorkflow(ProcessBlob)
	w.RegisterWorkflow(Maintenance)
	w.RegisterActivityWithOptions(s.provisionInitialStorages, activity.RegisterOptions{Name: "ProvisionInitialStorages"})
	w.RegisterActivityWithOptions(s.provisionMemberStorage, activity.RegisterOptions{Name: "ProvisionMemberStorageResources"})
	w.RegisterActivityWithOptions(s.deleteWorkspaceStorage, activity.RegisterOptions{Name: "DeleteWorkspaceStorage"})
	w.RegisterActivityWithOptions(s.reportProcessingFailure, activity.RegisterOptions{Name: "ReportProcessingFailure"})
	w.RegisterActivityWithOptions(s.maintenance, activity.RegisterOptions{Name: "LetFSMaintenance"})
}
func ProcessBlob(ctx workflow.Context, in ProcessInput) error {
	options := workflow.ActivityOptions{StartToCloseTimeout: time.Duration(in.ParseTimeoutSeconds) * time.Second, TaskQueue: in.CPUQueue, HeartbeatTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 3}}
	var err error
	if in.ParseRequired {
		err = workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, options), "ParseBlob", in).Get(ctx, nil)
	}
	if err == nil {
		options.TaskQueue = in.IOQueue
		options.StartToCloseTimeout = time.Duration(in.EnrichTimeoutSeconds) * time.Second
		err = workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, options), "EnrichAndIndex", in).Get(ctx, nil)
	}
	if err != nil {
		reportCtx := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: time.Minute, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 3}})
		if reportErr := workflow.ExecuteActivity(reportCtx, "ReportProcessingFailure", in).Get(ctx, nil); reportErr != nil {
			return reportErr
		}
	}
	return err
}
func (s *Server) dispatch(ctx context.Context, id string, version int64, parseRequired bool) error {
	in := ProcessInput{FileID: id, Version: version, ParseRequired: parseRequired, CPUQueue: s.Queues.IngestCPU, IOQueue: s.Queues.IngestIO, ParseTimeoutSeconds: s.Settings.Processing.ParseTimeoutSeconds, EnrichTimeoutSeconds: s.Settings.Processing.EnrichIndexTimeoutSeconds}
	_, err := s.Temporal.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: fmt.Sprintf("process/%s/%d", id, version), TaskQueue: s.Queues.LetFS, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING}, ProcessBlob, in)
	var already *serviceerror.WorkflowExecutionAlreadyStarted
	if errors.As(err, &already) {
		return nil
	}
	return err
}
func (s *Server) reportProcessingFailure(ctx context.Context, in ProcessInput) error {
	_, err := s.FailProcessing(ctx, &pb.FailProcessingRequest{FileId: in.FileID, Version: in.Version, ErrorCode: "PROCESSING_FAILED"})
	return err
}
func Maintenance(ctx workflow.Context) error {
	return workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 5 * time.Minute, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 1}}), "LetFSMaintenance").Get(ctx, nil)
}
