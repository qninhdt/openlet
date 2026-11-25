package storage

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/jackc/pgx/v5"
	"github.com/qdrant/go-client/qdrant"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
)

type ProcessBlobInput struct {
	BlobID               string `json:"blob_id"`
	ParseRequired        bool   `json:"parse_required"`
	Attempt              int64  `json:"attempt"`
	CPUQueue             string `json:"cpu_queue"`
	IOQueue              string `json:"io_queue"`
	ParseTimeoutSeconds  int    `json:"parse_timeout_seconds"`
	EnrichTimeoutSeconds int    `json:"enrich_timeout_seconds"`
}

func RegisterWorker(w worker.Worker, s *Server) {
	w.RegisterWorkflow(ProcessBlob)
	w.RegisterWorkflow(CleanupBlob)
	w.RegisterWorkflow(Maintenance)
	w.RegisterActivityWithOptions(s.provisionInitialStorages, activity.RegisterOptions{Name: "ProvisionInitialStorages"})
	w.RegisterActivityWithOptions(s.provisionMemberStorage, activity.RegisterOptions{Name: "ProvisionMemberStorageResources"})
	w.RegisterActivityWithOptions(s.deleteWorkspaceStorage, activity.RegisterOptions{Name: "DeleteWorkspaceStorage"})
	w.RegisterActivityWithOptions(s.reportBlobFailure, activity.RegisterOptions{Name: "ReportBlobFailure"})
	w.RegisterActivityWithOptions(s.terminateBlobProcessing, activity.RegisterOptions{Name: "TerminateBlobProcessing"})
	w.RegisterActivityWithOptions(s.deleteBlobIndex, activity.RegisterOptions{Name: "DeleteBlobIndex"})
	w.RegisterActivityWithOptions(s.deleteBlobObjects, activity.RegisterOptions{Name: "DeleteBlobObjects"})
	w.RegisterActivityWithOptions(s.deleteBlobRecord, activity.RegisterOptions{Name: "DeleteBlobRecord"})
	w.RegisterActivityWithOptions(s.maintenance, activity.RegisterOptions{Name: "LetFSMaintenance"})
}

func ProcessBlob(ctx workflow.Context, in ProcessBlobInput) error {
	if in.ParseRequired {
		parseOpts := workflow.ActivityOptions{
			StartToCloseTimeout: time.Duration(in.ParseTimeoutSeconds) * time.Second,
			TaskQueue:           in.CPUQueue,
			HeartbeatTimeout:    30 * time.Second,
			RetryPolicy:         &temporal.RetryPolicy{MaximumAttempts: 3},
		}
		if err := workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, parseOpts), "ParseBlob", in.BlobID).Get(ctx, nil); err != nil {
			reportFailure(ctx, in)
			return err
		}
	}
	ioOpts := workflow.ActivityOptions{
		StartToCloseTimeout: time.Duration(in.EnrichTimeoutSeconds) * time.Second,
		TaskQueue:           in.IOQueue,
		HeartbeatTimeout:    30 * time.Second,
		RetryPolicy:         &temporal.RetryPolicy{MaximumAttempts: 3},
	}
	if err := workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, ioOpts), "EnrichBlob", in.BlobID).Get(ctx, nil); err != nil {
		reportFailure(ctx, in)
		return err
	}
	if err := workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, ioOpts), "IndexBlob", in.BlobID).Get(ctx, nil); err != nil {
		reportFailure(ctx, in)
		return err
	}
	return nil
}

func reportFailure(ctx workflow.Context, in ProcessBlobInput) {
	info := workflow.GetInfo(ctx)
	dctx, _ := workflow.NewDisconnectedContext(ctx)
	opts := workflow.ActivityOptions{
		StartToCloseTimeout: 30 * time.Second,
		TaskQueue:           info.TaskQueueName,
		RetryPolicy:         &temporal.RetryPolicy{MaximumAttempts: 3},
	}
	_ = workflow.ExecuteActivity(workflow.WithActivityOptions(dctx, opts), "ReportBlobFailure", in).Get(dctx, nil)
}

func CleanupBlob(ctx workflow.Context, blobID string) error {
	info := workflow.GetInfo(ctx)
	opts := workflow.ActivityOptions{
		StartToCloseTimeout: time.Minute,
		TaskQueue:           info.TaskQueueName,
		RetryPolicy:         &temporal.RetryPolicy{MaximumAttempts: 5},
	}
	actCtx := workflow.WithActivityOptions(ctx, opts)
	if err := workflow.ExecuteActivity(actCtx, "TerminateBlobProcessing", blobID).Get(ctx, nil); err != nil {
		return err
	}
	if err := workflow.ExecuteActivity(actCtx, "DeleteBlobIndex", blobID).Get(ctx, nil); err != nil {
		return err
	}
	if err := workflow.ExecuteActivity(actCtx, "DeleteBlobObjects", blobID).Get(ctx, nil); err != nil {
		return err
	}
	return workflow.ExecuteActivity(actCtx, "DeleteBlobRecord", blobID).Get(ctx, nil)
}

func Maintenance(ctx workflow.Context) error {
	options := workflow.ActivityOptions{StartToCloseTimeout: 5 * time.Minute, RetryPolicy: &temporal.RetryPolicy{MaximumAttempts: 1}}
	return workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, options), "LetFSMaintenance").Get(ctx, nil)
}

func blobWorkflowID(blobID string, attempt int64) string {
	return fmt.Sprintf("blob/%s/%d", blobID, attempt)
}

func (s *Server) dispatchBlob(ctx context.Context, blobID string, parseRequired bool, attempt int64) error {
	if s.Temporal == nil {
		return nil
	}
	in := ProcessBlobInput{
		BlobID:               blobID,
		ParseRequired:        parseRequired,
		Attempt:              attempt,
		CPUQueue:             s.Queues.IngestCPU,
		IOQueue:              s.Queues.IngestIO,
		ParseTimeoutSeconds:  s.Settings.Processing.ParseTimeoutSeconds,
		EnrichTimeoutSeconds: s.Settings.Processing.EnrichIndexTimeoutSeconds,
	}
	_, err := s.Temporal.ExecuteWorkflow(ctx, client.StartWorkflowOptions{
		ID:                       blobWorkflowID(blobID, attempt),
		TaskQueue:                s.Queues.LetFS,
		WorkflowIDReusePolicy:    enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE,
		WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING,
	}, ProcessBlob, in)
	var already *serviceerror.WorkflowExecutionAlreadyStarted
	if errors.As(err, &already) {
		return nil
	}
	return err
}

func (s *Server) dispatchCleanupBlob(ctx context.Context, blobID string) error {
	if s.Temporal == nil || blobID == "" {
		return nil
	}
	_, err := s.Temporal.ExecuteWorkflow(ctx, client.StartWorkflowOptions{
		ID:                       "cleanup-blob/" + blobID,
		TaskQueue:                s.Queues.LetFS,
		WorkflowIDReusePolicy:    enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE,
		WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING,
	}, CleanupBlob, blobID)
	var already *serviceerror.WorkflowExecutionAlreadyStarted
	if errors.As(err, &already) {
		return nil
	}
	return err
}

func (s *Server) reportBlobFailure(ctx context.Context, in ProcessBlobInput) error {
	_, err := s.DB.Exec(ctx, `UPDATE blobs SET processing_stage='failed',processing_error_code='PROCESSING_FAILED' WHERE id=$1 AND delete_requested_at IS NULL AND processing_stage<>'ready' AND processing_attempt=$2`, in.BlobID, in.Attempt)
	return err
}

func (s *Server) terminateBlobProcessing(ctx context.Context, blobID string) error {
	if s.Temporal == nil {
		return nil
	}
	var attempt int64
	err := s.DB.QueryRow(ctx, `SELECT processing_attempt FROM blobs WHERE id=$1`, blobID).Scan(&attempt)
	if err == pgx.ErrNoRows {
		return nil
	}
	if err != nil {
		return err
	}
	err = s.Temporal.TerminateWorkflow(ctx, blobWorkflowID(blobID, attempt), "", "blob deleted")
	var notFoundErr *serviceerror.NotFound
	if errors.As(err, &notFoundErr) {
		return nil
	}
	return err
}

func (s *Server) deleteBlobIndex(ctx context.Context, blobID string) error {
	if s.Qdrant == nil {
		return nil
	}
	_, err := s.Qdrant.Delete(ctx, &qdrant.DeletePoints{
		CollectionName: s.Collection,
		Points: qdrant.NewPointsSelectorFilter(&qdrant.Filter{
			Must: []*qdrant.Condition{qdrant.NewMatchKeyword("blob_id", blobID)},
		}),
		Wait:     aws.Bool(true),
		Ordering: &qdrant.WriteOrdering{Type: qdrant.WriteOrderingType_Strong},
	})
	return err
}

func (s *Server) deleteBlobObjects(ctx context.Context, blobID string) error {
	if s.S3 == nil {
		return nil
	}
	var workspaceID string
	err := s.DB.QueryRow(ctx, `SELECT workspace_id::text FROM blobs WHERE id=$1`, blobID).Scan(&workspaceID)
	if err == pgx.ErrNoRows {
		return nil
	}
	if err != nil {
		return err
	}
	return s.deleteS3Prefix(ctx, fmt.Sprintf("workspaces/%s/blobs/%s/", workspaceID, blobID))
}

func (s *Server) deleteBlobRecord(ctx context.Context, blobID string) error {
	_, err := s.DB.Exec(ctx, `DELETE FROM blobs WHERE id=$1 AND delete_requested_at IS NOT NULL`, blobID)
	return err
}

func (s *Server) deleteS3Prefix(ctx context.Context, prefix string) error {
	if s.S3 == nil {
		return nil
	}
	pages := s3.NewListObjectsV2Paginator(s.S3, &s3.ListObjectsV2Input{Bucket: &s.Bucket, Prefix: &prefix})
	for pages.HasMorePages() {
		page, err := pages.NextPage(ctx)
		if err != nil {
			return err
		}
		if len(page.Contents) == 0 {
			continue
		}
		objects := make([]types.ObjectIdentifier, 0, len(page.Contents))
		for _, item := range page.Contents {
			if item.Key != nil {
				objects = append(objects, types.ObjectIdentifier{Key: item.Key})
			}
		}
		if len(objects) > 0 {
			res, err := s.S3.DeleteObjects(ctx, &s3.DeleteObjectsInput{
				Bucket: &s.Bucket,
				Delete: &types.Delete{Objects: objects, Quiet: aws.Bool(true)},
			})
			if err != nil {
				return err
			}
			if len(res.Errors) > 0 {
				return fmt.Errorf("delete s3 objects under %s failed (%d errors)", prefix, len(res.Errors))
			}
		}
	}
	uploads := s3.NewListMultipartUploadsPaginator(s.S3, &s3.ListMultipartUploadsInput{Bucket: &s.Bucket, Prefix: &prefix})
	for uploads.HasMorePages() {
		page, err := uploads.NextPage(ctx)
		if err != nil {
			return err
		}
		for _, u := range page.Uploads {
			_, _ = s.S3.AbortMultipartUpload(ctx, &s3.AbortMultipartUploadInput{Bucket: &s.Bucket, Key: u.Key, UploadId: u.UploadId})
		}
	}
	return nil
}

type pendingS3Object struct {
	key       string
	multipart *string
}

func (s *Server) abortAndDeleteS3Object(ctx context.Context, key string, multipart *string) error {
	if s.S3 == nil {
		return nil
	}
	if multipart != nil {
		if _, err := s.S3.AbortMultipartUpload(ctx, &s3.AbortMultipartUploadInput{Bucket: &s.Bucket, Key: &key, UploadId: multipart}); err != nil && key == "" {
			return err
		}
	}
	_, err := s.S3.DeleteObject(ctx, &s3.DeleteObjectInput{Bucket: &s.Bucket, Key: &key})
	return err
}

func markOrphanBlobs(ctx context.Context, tx pgx.Tx, blobIDs []string) ([]string, error) {
	if len(blobIDs) == 0 {
		return nil, nil
	}
	rows, err := tx.Query(ctx, `UPDATE blobs b SET delete_requested_at=now() WHERE b.id=ANY($1::uuid[]) AND b.delete_requested_at IS NULL AND NOT EXISTS(SELECT 1 FROM files f WHERE f.blob_id=b.id) AND NOT EXISTS(SELECT 1 FROM uploads u WHERE u.blob_id=b.id AND u.result IS NULL) RETURNING b.id::text`, blobIDs)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var orphaned []string
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			return nil, err
		}
		orphaned = append(orphaned, id)
	}
	return orphaned, rows.Err()
}
