package temporal

import (
	"context"
	"errors"
	"time"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type Activities struct {
	Store *filesystem.Store
	Jobs  *Jobs
}

func activityError(err error) error {
	if err == nil {
		return nil
	}
	if errors.Is(err, context.Canceled) || status.Code(err) == codes.Canceled {
		return temporal.NewCanceledError()
	}
	reason := "DEPENDENCY_UNAVAILABLE"
	fault := status.Convert(err)
	for _, detail := range fault.Details() {
		if info, ok := detail.(*errdetails.ErrorInfo); ok && info.Domain == "openlet" {
			reason = info.Reason
		}
	}
	switch fault.Code() {
	case codes.InvalidArgument, codes.Unauthenticated, codes.PermissionDenied, codes.NotFound, codes.AlreadyExists, codes.FailedPrecondition, codes.Aborted, codes.OutOfRange, codes.ResourceExhausted:
		return temporal.NewNonRetryableApplicationError(reason, reason, nil)
	default:
		return temporal.NewApplicationError(reason, reason)
	}
}
func heartbeat(ctx context.Context) func() {
	stop, cancel := context.WithCancel(ctx)
	done := make(chan struct{})
	go func() {
		defer close(done)
		timer := time.NewTicker(10 * time.Second)
		defer timer.Stop()
		for {
			select {
			case <-stop.Done():
				return
			case <-timer.C:
				activity.RecordHeartbeat(stop)
			}
		}
	}()
	return func() { cancel(); <-done }
}
func (a *Activities) CopyItem(ctx context.Context, step CopyStep) error {
	stop := heartbeat(ctx)
	defer stop()
	return activityError(a.Store.CommitCopyItem(ctx, step.Admission, step.Item))
}
func (a *Activities) NextCopyItem(ctx context.Context, input CopyNext) (*filesystem.CopyItem, error) {
	item, err := a.Store.NextCopyItem(ctx, input.Admission, input.Frame)
	return item, activityError(err)
}
func (a *Activities) FinishCopyFile(ctx context.Context, input CopyNext) error {
	return activityError(a.Store.FinishCopyFile(ctx, input.Admission, input.Frame))
}
func (a *Activities) CompleteCopy(ctx context.Context, admission filesystem.CopyAdmission) error {
	return activityError(a.Store.CompleteCopy(ctx, admission))
}

func (a *Activities) DeleteNodesBatch(ctx context.Context, input DeletionInput) (bool, error) {
	done, err := a.Store.DeletionBatch(ctx, input.FilesystemID, input.EntryID)
	return done, activityError(err)
}
