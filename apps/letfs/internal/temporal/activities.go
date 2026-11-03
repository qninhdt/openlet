package temporal

import (
	"context"
	"time"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	sharedtemporal "github.com/qninhdt/openlet/packages/go/temporal"
	"go.temporal.io/sdk/activity"
)

type Activities struct {
	Store *filesystem.Store
	Jobs  *Jobs
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
	return sharedtemporal.Error(a.Store.CommitCopyItem(ctx, step.Admission, step.Item))
}
func (a *Activities) NextCopyItem(ctx context.Context, input CopyNext) (*filesystem.CopyItem, error) {
	item, err := a.Store.NextCopyItem(ctx, input.Admission, input.Frame)
	return item, sharedtemporal.Error(err)
}
func (a *Activities) FinishCopyFile(ctx context.Context, input CopyNext) error {
	return sharedtemporal.Error(a.Store.FinishCopyFile(ctx, input.Admission, input.Frame))
}
func (a *Activities) CompleteCopy(ctx context.Context, admission filesystem.CopyAdmission) error {
	return sharedtemporal.Error(a.Store.CompleteCopy(ctx, admission))
}

func (a *Activities) DeleteNodesBatch(ctx context.Context, input filesystem.DeletionInput) (bool, error) {
	done, err := a.Store.DeletionBatch(ctx, input.FilesystemID, input.EntryID)
	return done, sharedtemporal.Error(err)
}
