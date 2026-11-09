//go:build integration

package account

import (
	"github.com/qninhdt/openlet/apps/account/internal/testfixture"
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func TestIntegrationIdentityAndProfile(t *testing.T) {
	db := testfixture.Postgres(t)
	store := Store{DB: db}
	ctx := t.Context()
	// Concurrent first-login calls must converge on every persisted identity.
	const calls = 8
	results := make(chan uuid.UUID, calls)
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
	var original uuid.UUID
	for v := range results {
		if original == uuid.Nil {
			original = v
		}
		require.Equal(t, original, v)
	}
	require.Equal(t, uuid.Version(7), original.Version())
	_, err := store.Profile(ctx, original)
	require.NoError(t, err)
	name, avatar := "Việt Nam", "https://example.com/avatar.png"
	p, err := store.UpdateProfile(ctx, original, &name, &avatar)
	require.NoError(t, err)
	require.Equal(t, name, p.DisplayName)
	p, err = store.Profile(ctx, original)
	require.NoError(t, err)
	require.Equal(t, avatar, p.AvatarURL)
	other, err := store.EnsureUser(ctx, "user-other")
	require.NoError(t, err)
	summaries, err := store.Summaries(ctx, []uuid.UUID{original, other})
	require.NoError(t, err)
	require.Len(t, summaries, 2)
	invalid := "http://example.com/insecure"
	_, err = store.UpdateProfile(ctx, original, nil, &invalid)
	require.EqualError(t, err, "VALIDATION")
	invalid = "name\x00suffix"
	_, err = store.UpdateProfile(ctx, original, &invalid, nil)
	require.EqualError(t, err, "VALIDATION")
	unchanged, err := store.Profile(ctx, original)
	require.NoError(t, err)
	require.Equal(t, p, unchanged)
}
