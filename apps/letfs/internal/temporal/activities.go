package temporal

import (
	"context"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/identity"
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
func (a *Activities) CreateFilesystem(ctx context.Context, in sharedtemporal.FilesystemCreation) error {
	ctx = identity.WithPrincipal(ctx, identity.Principal{Service: "temporal"})
	_, err := a.Store.CreateFilesystem(ctx, in.Key, filesystem.CreateFilesystem{ID: in.ID, LimitBytes: in.LimitBytes})
	return sharedtemporal.Error(err)
}
func (a *Activities) CreateScopes(ctx context.Context, in sharedtemporal.ScopesCreation) error {
	ctx = identity.WithPrincipal(ctx, identity.Principal{Service: "temporal"})
	_, err := a.Store.CreateScopes(ctx, in.Key, in.FilesystemID, in.IDs, in.AllowBlobFiles, in.AllowIndexing)
	return sharedtemporal.Error(err)
}
func (a *Activities) ListScopesForDeletion(ctx context.Context, in sharedtemporal.FilesystemDeletion) ([]uuid.UUID, error) {
	values, err := a.Store.ListScopesForDeletion(ctx, in.FilesystemID, in.After)
	return values, sharedtemporal.Error(err)
}
func (a *Activities) RemoveFilesystem(ctx context.Context, id uuid.UUID) error {
	return sharedtemporal.Error(a.Store.RemoveFilesystem(ctx, id))
}
func (a *Activities) DeleteScopeData(ctx context.Context, in sharedtemporal.ScopeDeletion) error {
	stop := heartbeat(ctx)
	defer stop()
	return sharedtemporal.Error(a.Store.DeleteScopeData(ctx, in.FilesystemID, in.ScopeID))
}
