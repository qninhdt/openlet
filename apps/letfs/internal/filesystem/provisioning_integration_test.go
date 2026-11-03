//go:build integration

package filesystem

import (
	"context"
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"openlet/apps/letfs/internal/testfixture"
	"openlet/packages/go/identity"
)

func TestIntegrationStableProvisioningIdentity(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	s := &Store{DB: db, MaxNodes: 100}
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "workspace"})
	other := identity.WithPrincipal(t.Context(), identity.Principal{Service: "other-resource"})
	id, key := uuid.Must(uuid.NewV7()), uuid.New()
	input := CreateBucket{ID: id, LimitBytes: 100}
	concurrent := func(run func() error) {
		t.Helper()
		start, results := make(chan struct{}), make(chan error, 8)
		var workers sync.WaitGroup
		for range 8 {
			workers.Go(func() { <-start; results <- run() })
		}
		close(start)
		workers.Wait()
		close(results)
		for err := range results {
			require.NoError(t, err)
		}
	}
	concurrent(func() error { _, err := s.CreateBucket(ctx, key, input); return err })
	var count int
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM quota_buckets").Scan(&count))
	require.Equal(t, 1, count)
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM idempotency_keys").Scan(&count))
	require.Equal(t, 1, count)
	_, err := s.CreateBucket(ctx, key, CreateBucket{ID: id, LimitBytes: 101})
	require.Equal(t, codes.Aborted, status.Code(err))
	rollbackID := uuid.Must(uuid.NewV7())
	_, err = s.CreateBucket(ctx, key, CreateBucket{ID: rollbackID, LimitBytes: 100})
	require.Equal(t, codes.Aborted, status.Code(err))
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM quota_buckets WHERE id=$1", rollbackID).Scan(&count))
	require.Zero(t, count, "idempotency conflict rolls back the entire resource creation")
	otherID := uuid.Must(uuid.NewV7())
	_, err = s.CreateBucket(other, key, CreateBucket{ID: otherID, LimitBytes: 100})
	require.NoError(t, err, "request key namespace belongs to the verified caller")

	fsInput := CreateFilesystem{ID: uuid.Must(uuid.NewV7()), BucketID: id, RootName: "files"}
	fsKey := uuid.New()
	concurrent(func() error { _, err := s.CreateFilesystem(ctx, fsKey, fsInput); return err })
	fs, err := s.CreateFilesystem(ctx, uuid.New(), fsInput)
	require.NoError(t, err)
	require.NotNil(t, fs.RootID)
	require.NoError(t, db.QueryRow(ctx, "SELECT count(*) FROM nodes WHERE filesystem_id=$1", fs.ID).Scan(&count))
	require.Equal(t, 1, count, "all attempts converge on one root")
	changed := fsInput
	changed.RootName = "different"
	_, err = s.CreateFilesystem(ctx, fsKey, changed)
	require.Equal(t, codes.Aborted, status.Code(err))
	wrongRoot := uuid.New()
	require.Error(t, s.ReleaseProvisioning(ctx, id, fs.ID, wrongRoot))
	require.NoError(t, s.ReleaseProvisioning(ctx, id, fs.ID, *fs.RootID))
	require.NoError(t, s.ReleaseProvisioning(ctx, id, fs.ID, *fs.RootID))
	_, err = db.Exec(ctx, "UPDATE idempotency_keys SET expires_at=now()-interval '1 hour' WHERE scope='service:workspace'")
	require.NoError(t, err)
	require.NoError(t, s.PruneReceipts(ctx))
	resumed, err := s.CreateFilesystem(ctx, uuid.New(), fsInput)
	require.NoError(t, err)
	require.Equal(t, fs, resumed, "expired receipts cannot change admitted identity or allocate another root")
	_, err = db.Exec(ctx, "UPDATE quota_buckets SET limit_bytes=200 WHERE id=$1", id)
	require.NoError(t, err)
	_, err = s.CreateBucket(ctx, key, input)
	require.NoError(t, err, "retry identity refers to immutable creation parameters, not mutable quota")
	_, err = s.CreateBucket(ctx, uuid.New(), CreateBucket{ID: id, LimitBytes: 200})
	require.NoError(t, err, "new requests do not compare against a permanent creation fingerprint")
	_, err = s.CompleteBucketDeletion(ctx, uuid.New(), id)
	require.Error(t, err, "active bucket cannot finish deletion")
	_, err = s.FreezeBucket(ctx, uuid.New(), id)
	require.NoError(t, err)
	ids, err := s.ListBucketFilesystems(ctx, id, uuid.Nil)
	require.NoError(t, err)
	require.Equal(t, []uuid.UUID{fs.ID}, ids)
	_, err = s.CreateFilesystem(ctx, uuid.New(), fsInput)
	require.Error(t, err, "a new receipt cannot bypass a frozen bucket")
	_, err = s.CompleteBucketDeletion(ctx, uuid.New(), id)
	require.Error(t, err, "live filesystem blocks bucket deletion")

	t.Run("freeze unknown stable ID then late create", func(t *testing.T) {
		fencedID := uuid.Must(uuid.NewV7())
		frozen, err := s.FreezeBucket(ctx, uuid.New(), fencedID)
		require.NoError(t, err)
		require.Equal(t, "frozen", frozen.State)
		late := CreateBucket{ID: fencedID, LimitBytes: 500}
		_, err = s.CreateBucket(ctx, uuid.New(), late)
		require.Error(t, err)
		deleted, err := s.CompleteBucketDeletion(ctx, uuid.New(), fencedID)
		require.NoError(t, err)
		require.Equal(t, "deleted", deleted.State)
		_, err = db.Exec(ctx, "UPDATE idempotency_keys SET expires_at=now()-interval '1 hour' WHERE result->>'id'=$1", fencedID.String())
		require.NoError(t, err)
		require.NoError(t, s.PruneReceipts(ctx))
		_, err = s.CreateBucket(ctx, uuid.New(), late)
		require.Error(t, err, "deleted tombstone survives receipt expiry")
		var state string
		require.NoError(t, db.QueryRow(ctx, "SELECT state FROM quota_buckets WHERE id=$1", fencedID).Scan(&state))
		require.Equal(t, "deleted", state)
	})
}

func TestIntegrationFreezeSerializesConcurrentCreation(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	s := Store{DB: db, MaxNodes: 100}
	ctx, cancel := context.WithCancel(identity.WithPrincipal(t.Context(), identity.Principal{Service: "generic-owner"}))
	defer cancel()
	for range 8 {
		id := uuid.Must(uuid.NewV7())
		start, results := make(chan struct{}), make(chan error, 2)
		go func() {
			<-start
			_, err := s.CreateBucket(ctx, uuid.New(), CreateBucket{ID: id, LimitBytes: 1})
			results <- err
		}()
		go func() { <-start; _, err := s.FreezeBucket(ctx, uuid.New(), id); results <- err }()
		close(start)
		for range 2 {
			err := <-results
			if err != nil {
				require.Equal(t, codes.FailedPrecondition, status.Code(err))
			}
		}
		var state string
		require.NoError(t, db.QueryRow(ctx, "SELECT state FROM quota_buckets WHERE id=$1", id).Scan(&state))
		require.Equal(t, "frozen", state, "either serialization order fences subsequent creation")
	}
}
