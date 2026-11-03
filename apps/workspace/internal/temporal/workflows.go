package temporal

import (
	"context"
	"errors"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/letfs"
	"github.com/qninhdt/openlet/apps/workspace/internal/user"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"
	"strconv"
	"time"
)

const Queue = "openlet-workspace"

type Activities struct {
	Store   *workspace.Store
	Graph   v1.PermissionsServiceClient
	Storage letfsv1.StorageAdministrationServiceClient
	User    user.Client
}

func businessError(err error) error {
	var fault workspace.Fault
	if errors.As(err, &fault) {
		return temporal.NewNonRetryableApplicationError(fault.Code, fault.Code, err)
	}
	return err
}

type Provisioning struct {
	Workspace workspace.Workspace
	Storage   workspace.Storage
}

func (a *Activities) PrepareWorkspace(ctx context.Context, in workspace.CreateInput) (Provisioning, error) {
	value, err := a.Store.EnsureWorkspace(ctx, in)
	if err != nil {
		return Provisioning{}, businessError(err)
	}
	storage, err := a.Store.ReserveStorage(ctx, value.ID)
	if err != nil {
		return Provisioning{}, businessError(err)
	}
	if err = a.Store.InitializeRelationships(ctx, a.Graph, value.ID); err != nil {
		return Provisioning{}, err
	}
	return Provisioning{Workspace: value, Storage: storage}, nil
}

func (a *Activities) CompleteWorkspace(ctx context.Context, storage workspace.Storage, in workspace.CreateInput) error {
	if err := a.Store.PublishActivationRelationships(ctx, a.Graph, storage.WorkspaceID); err != nil {
		return businessError(err)
	}
	if err := a.Store.Activate(ctx, storage); err != nil {
		return businessError(err)
	}
	if _, err := a.Storage.ReleaseProvisioning(ctx, provisioned(storage)); err != nil {
		return err
	}
	return a.Store.CompleteCreation(ctx, in)
}

func provisioned(value workspace.Storage) *letfsv1.ReleaseProvisioningRequest {
	return &letfsv1.ReleaseProvisioningRequest{BucketId: value.BucketID.String(), FilesystemId: value.FilesystemID.String(), RootId: value.RootID.String()}
}

func (a *Activities) FailWorkspace(ctx context.Context, in workspace.CreateInput) error {
	value, found, err := a.Store.FindCreation(ctx, in)
	if err != nil || !found {
		return businessError(err)
	}
	if err := a.Store.Fail(ctx, value.ID); err != nil {
		return err
	}
	return a.Store.PublishStorageRelationships(ctx, a.Graph, value.ID)
}

func CreateWorkspace(ctx workflow.Context, in workspace.CreateInput) (result uuid.UUID, err error) {
	ctx = workflow.WithActivityOptions(ctx, workflow.ActivityOptions{StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var prepared Provisioning
	var admissionErr error
	ready := false
	if err = workflow.SetUpdateHandler(ctx, "admission", func(ctx workflow.Context, requested workspace.CreateInput) (workspace.Workspace, error) {
		if requested != in {
			return workspace.Workspace{}, temporal.NewNonRetryableApplicationError("idempotency conflict", "IDEMPOTENCY_CONFLICT", nil)
		}
		if err := workflow.Await(ctx, func() bool { return ready }); err != nil {
			return workspace.Workspace{}, err
		}
		return prepared.Workspace, admissionErr
	}); err != nil {
		return uuid.Nil, err
	}
	defer func() { _ = workflow.Await(ctx, func() bool { return workflow.AllHandlersFinished(ctx) }) }()
	var a *Activities
	defer func() {
		if err != nil {
			cleanup, cancel := workflow.NewDisconnectedContext(ctx)
			defer cancel()
			_ = workflow.ExecuteActivity(cleanup, a.FailWorkspace, in).Get(cleanup, nil)
		}
	}()
	admissionErr = workflow.ExecuteActivity(ctx, a.PrepareWorkspace, in).Get(ctx, &prepared)
	ready = true
	if admissionErr != nil {
		return uuid.Nil, admissionErr
	}
	result = prepared.Workspace.ID
	mapping := prepared.Storage
	limit, parseErr := strconv.ParseInt(mapping.LimitBytes, 10, 64)
	if parseErr != nil {
		return result, temporal.NewNonRetryableApplicationError("invalid quota", "STATE_CONFLICT", parseErr)
	}
	remote := workflow.WithActivityOptions(ctx, workflow.ActivityOptions{TaskQueue: letfs.Queue, StartToCloseTimeout: 30 * time.Second, RetryPolicy: &temporal.RetryPolicy{InitialInterval: time.Second, MaximumInterval: 30 * time.Second}})
	var storage letfsv1.CreateStorageResponse
	err = workflow.ExecuteActivity(remote, letfs.CreateStorage, "workspace", &letfsv1.CreateStorageRequest{
		Bucket:     &letfsv1.CreateBucketRequest{BucketId: mapping.BucketID.String(), IdempotencyKey: mapping.BucketID.String(), LimitBytes: limit},
		Filesystem: &letfsv1.CreateFilesystemRequest{FilesystemId: mapping.FilesystemID.String(), BucketId: mapping.BucketID.String(), IdempotencyKey: mapping.FilesystemID.String(), RootName: "drive"},
	}).Get(remote, &storage)
	if err != nil {
		return result, err
	}
	fs := storage.GetFilesystem()
	bucket := storage.GetBucket()
	root, parseErr := uuid.Parse(fs.GetRootId())
	if parseErr != nil || root == uuid.Nil || fs.GetId() != mapping.FilesystemID.String() || fs.GetBucketId() != mapping.BucketID.String() || fs.GetState() != "active" || bucket.GetId() != mapping.BucketID.String() || bucket.GetState() != "active" || bucket.GetLimitBytes() != limit {
		return result, temporal.NewNonRetryableApplicationError("invalid storage result", "STORAGE_SCOPE_CONFLICT", parseErr)
	}
	mapping.RootID = root
	err = workflow.ExecuteActivity(ctx, a.CompleteWorkspace, mapping, in).Get(ctx, nil)
	return result, err
}

func StartCreate(ctx context.Context, tc client.Client, in workspace.CreateInput) (workspace.Workspace, error) {
	operation := tc.NewWithStartWorkflowOperation(client.StartWorkflowOptions{ID: "create-workspace/" + in.ActorID.String() + "/" + in.Key.String(), TaskQueue: Queue, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_ALLOW_DUPLICATE, WorkflowExecutionTimeout: 7 * 24 * time.Hour}, CreateWorkspace, in)
	handle, err := tc.UpdateWithStartWorkflow(ctx, client.UpdateWithStartWorkflowOptions{StartWorkflowOperation: operation, UpdateOptions: client.UpdateWorkflowOptions{UpdateName: "admission", Args: []any{in}, WaitForStage: client.WorkflowUpdateStageAccepted}})
	if err != nil {
		return workspace.Workspace{}, err
	}
	var value workspace.Workspace
	err = handle.Get(ctx, &value)
	return value, err
}
