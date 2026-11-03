package temporal

import (
	"context"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/letfs"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"time"
)

type DeleteWorkflowInput struct {
	Workspace workspace.Workspace `json:"workspace"`
	Cursor    uuid.UUID           `json:"cursor"`
}

func (a *Activities) PrepareWorkspaceDeletion(ctx context.Context, in workspace.DeleteInput) (workspace.Workspace, error) {
	value, err := a.Store.BeginDeletion(ctx, in)
	if err != nil {
		return value, businessError(err)
	}
	err = a.Store.PublishStorageRelationships(ctx, a.Graph, value.ID)
	return value, err
}
func (a *Activities) CompleteWorkspaceDeletion(ctx context.Context, id uuid.UUID) error {
	if err := a.Store.CompleteDeletion(ctx, id); err != nil {
		return businessError(err)
	}
	return a.Store.DeleteMemberRelationships(ctx, a.Graph, id)
}
func DeleteWorkspace(ctx workflow.Context, in DeleteWorkflowInput) (uuid.UUID, error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	// Once admitted, cancellation must not strand destructive cleanup.
	ctx, cancel := workflow.NewDisconnectedContext(ctx)
	defer cancel()
	var a *Activities
	value := in.Workspace
	if value.Status == "deleted" {
		return value.ID, nil
	}
	if value.BucketID != nil {
		bucketID := value.BucketID.String()
		remote := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{TaskQueue: letfs.Queue, StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
		var bucket *letfsv1.Bucket
		if err := workflow.ExecuteActivity(remote, letfs.FreezeBucket, "workspace", &letfsv1.FreezeBucketRequest{BucketId: bucketID, IdempotencyKey: bucketID}).Get(ctx, &bucket); err != nil {
			return value.ID, err
		}
		if bucket.GetId() != bucketID || (bucket.GetState() != "frozen" && bucket.GetState() != "deleted") {
			return value.ID, temporal.NewNonRetryableApplicationError("invalid bucket result", "STORAGE_SCOPE_CONFLICT", nil)
		}
		count := 0
		for {
			request := &letfsv1.ListBucketFilesystemsRequest{BucketId: bucketID}
			if in.Cursor != uuid.Nil {
				after := in.Cursor.String()
				request.AfterId = &after
			}
			var page *letfsv1.ListBucketFilesystemsResponse
			if err := workflow.ExecuteActivity(remote, letfs.ListFilesystems, "workspace", request).Get(ctx, &page); err != nil {
				return value.ID, err
			}
			if len(page.GetFilesystemIds()) == 0 {
				break
			}
			for _, rawID := range page.GetFilesystemIds() {
				id, err := uuid.Parse(rawID)
				if err != nil || id == uuid.Nil || id.String() <= in.Cursor.String() {
					return value.ID, temporal.NewNonRetryableApplicationError("invalid filesystem page", "STORAGE_SCOPE_CONFLICT", err)
				}
				if err := workflow.ExecuteActivity(remote, letfs.PrepareDeletion, "workspace", id).Get(ctx, nil); err != nil {
					return value.ID, err
				}
				childCtx := workflow.WithChildOptions(ctx, workflow.ChildWorkflowOptions{WorkflowID: "delete-filesystem/" + id.String() + "/" + workflow.GetInfo(ctx).WorkflowExecution.RunID, TaskQueue: letfs.Queue, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, ParentClosePolicy: enums.PARENT_CLOSE_POLICY_ABANDON, WorkflowExecutionTimeout: 7 * 24 * time.Hour})
				child := workflow.ExecuteChildWorkflow(childCtx, "DeleteFilesystem", letfs.DeletionInput{FilesystemID: id})
				if err := child.GetChildWorkflowExecution().Get(ctx, nil); err != nil {
					return value.ID, err
				}
				if err := child.Get(ctx, nil); err != nil {
					return value.ID, err
				}
				in.Cursor = id
				count++
				if count >= 100 {
					return value.ID, workflow.NewContinueAsNewError(ctx, DeleteWorkspace, in)
				}
			}
		}
		if err := workflow.ExecuteActivity(remote, letfs.CompleteBucket, "workspace", &letfsv1.CompleteBucketDeletionRequest{BucketId: bucketID, IdempotencyKey: bucketID}).Get(ctx, &bucket); err != nil {
			return value.ID, err
		}
		if bucket.GetId() != bucketID || bucket.GetState() != "deleted" {
			return value.ID, temporal.NewNonRetryableApplicationError("invalid bucket result", "STORAGE_SCOPE_CONFLICT", nil)
		}
	}
	if err := workflow.ExecuteActivity(ctx, a.CompleteWorkspaceDeletion, value.ID).Get(ctx, nil); err != nil {
		return value.ID, err
	}
	return value.ID, nil
}
