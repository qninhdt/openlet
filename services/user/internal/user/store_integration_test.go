//go:build integration

package user

import (
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"openlet/tests/testinfra"
)

func TestIntegrationIdentityAndProfile(t *testing.T) {
	db := testinfra.Postgres(t, "user", "../../migrations")
	store := Store{DB: db}
	ctx := t.Context()
	// Concurrent first-login calls must converge on every persisted identity.
	const calls = 8
	results := make(chan Onboarding, calls)
	errors := make(chan error, calls)
	start := make(chan struct{})
	var workers sync.WaitGroup
	for range calls {
		workers.Go(func() {
			<-start
			v, err := store.EnsureUser(ctx, "user-testcontainers")
			results <- v
			errors <- err
		})
	}
	close(start)
	workers.Wait()
	close(results)
	close(errors)
	for err := range errors {
		require.NoError(t, err)
	}
	var original Onboarding
	for v := range results {
		if original.UserID == uuid.Nil {
			original = v
		}
		require.Equal(t, original, v)
	}
	require.Equal(t, uuid.Version(7), original.UserID.Version())
	_, err := store.Profile(ctx, original.UserID)
	require.EqualError(t, err, "NOT_FOUND")
	require.NoError(t, store.Complete(ctx, "user-testcontainers"))
	require.NoError(t, store.Complete(ctx, "user-testcontainers"))
	name, avatar := "Việt Nam", "https://example.com/avatar.png"
	p, err := store.UpdateProfile(ctx, original.UserID, &name, &avatar)
	require.NoError(t, err)
	require.Equal(t, name, p.DisplayName)
	p, err = store.Profile(ctx, original.UserID)
	require.NoError(t, err)
	require.Equal(t, avatar, p.AvatarURL)
	other, err := store.EnsureUser(ctx, "user-other")
	require.NoError(t, err)
	summaries, err := store.Summaries(ctx, []uuid.UUID{original.UserID, other.UserID})
	require.NoError(t, err)
	require.Equal(t, []Profile{p}, summaries)
	invalid := "http://example.com/insecure"
	_, err = store.UpdateProfile(ctx, original.UserID, nil, &invalid)
	require.EqualError(t, err, "VALIDATION")
	invalid = "name\x00suffix"
	_, err = store.UpdateProfile(ctx, original.UserID, &invalid, nil)
	require.EqualError(t, err, "VALIDATION")
	unchanged, err := store.Profile(ctx, original.UserID)
	require.NoError(t, err)
	require.Equal(t, p, unchanged)
	after, err := store.Onboarding(ctx, "user-testcontainers")
	require.NoError(t, err)
	require.Equal(t, original.UserID, after.UserID)
	require.Equal(t, original.WorkspaceID, after.WorkspaceID)
	require.Equal(t, "succeeded", after.State)
	require.True(t, after.RefreshSession)
}
