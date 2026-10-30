//go:build integration

package workspace

import (
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"openlet/tests/testinfra"
)

func TestIntegrationWorkspaceCollaboration(t *testing.T) {
	db := testinfra.Postgres(t, "workspace", "../../migrations")
	store := Store{DB: db, MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	ctx := t.Context()
	owner, member := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	input := CreateInput{ActorID: owner, Key: uuid.Must(uuid.NewV7()), Name: "Team"}
	created, err := store.EnsureWorkspace(ctx, input)
	require.NoError(t, err)
	again, err := store.EnsureWorkspace(ctx, input)
	require.NoError(t, err)
	require.Equal(t, created, again)
	changed := input
	changed.Name = "Different"
	_, err = store.EnsureWorkspace(ctx, changed)
	require.EqualError(t, err, "IDEMPOTENCY_CONFLICT")
	require.NoError(t, store.Activate(ctx, created.Operation.ID))
	ws := created.Operation.WorkspaceID
	_, err = store.Authorize(ctx, ws, member, "viewer")
	require.EqualError(t, err, "NOT_FOUND")
	invitation, token, err := store.Invite(ctx, ws, owner, "member@example.com", "editor")
	require.NoError(t, err)
	require.NotEmpty(t, invitation.ID)
	require.NotEmpty(t, token)
	_, err = store.AcceptInvite(ctx, member, token, []string{"other@example.com"})
	require.EqualError(t, err, "INVITATION_EMAIL_MISMATCH")
	accepted, err := store.AcceptInvite(ctx, member, token, []string{"MEMBER@example.com"})
	require.NoError(t, err)
	require.Equal(t, ws, accepted)
	_, err = store.AcceptInvite(ctx, member, token, []string{"member@example.com"})
	require.NoError(t, err)
	_, err = store.Authorize(ctx, ws, member, "editor")
	require.NoError(t, err)
	require.EqualError(t, store.ChangeMember(ctx, ws, owner, owner, "", true), "OWNER_TRANSFER_REQUIRED")
	require.NoError(t, store.Transfer(ctx, ws, owner, member))
	_, err = store.Authorize(ctx, ws, owner, "owner")
	require.EqualError(t, err, "FORBIDDEN")
	current, err := store.Authorize(ctx, ws, member, "owner")
	require.NoError(t, err)
	renamed, err := store.Rename(ctx, ws, member, "Renamed", current.Revision)
	require.NoError(t, err)
	_, err = store.Rename(ctx, ws, member, "Stale", current.Revision)
	require.EqualError(t, err, "REVISION_MISMATCH")
	require.NoError(t, store.ChangeMember(ctx, ws, member, owner, "", true))
	_, err = store.AcceptInvite(ctx, owner, token, []string{"member@example.com"})
	require.EqualError(t, err, "INVITATION_INVALID")
	deletion := DeleteInput{ActorID: member, WorkspaceID: ws, Key: uuid.Must(uuid.NewV7()), Revision: renamed.Revision}
	begun, err := store.BeginDeletion(ctx, deletion)
	require.NoError(t, err)
	repeated, err := store.BeginDeletion(ctx, deletion)
	require.NoError(t, err)
	require.Equal(t, begun.Operation.ID, repeated.Operation.ID)
	_, err = store.Authorize(ctx, ws, member, "owner")
	require.EqualError(t, err, "WORKSPACE_DELETING")
}

func TestIntegrationConcurrentWorkspaceLimit(t *testing.T) {
	db := testinfra.Postgres(t, "workspace", "../../migrations")
	store := Store{DB: db, MaxWorkspaces: 1, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	owner := uuid.Must(uuid.NewV7())
	start := make(chan struct{})
	results := make(chan error, 2)
	var workers sync.WaitGroup
	for range 2 {
		workers.Go(func() {
			<-start
			_, err := store.EnsureWorkspace(t.Context(), CreateInput{
				ActorID: owner,
				Key:     uuid.Must(uuid.NewV7()),
				Name:    "Concurrent",
			})
			results <- err
		})
	}
	close(start)
	workers.Wait()
	close(results)
	admitted, rejected := 0, 0
	for err := range results {
		if err == nil {
			admitted++
		} else {
			require.EqualError(t, err, "RESOURCE_LIMIT")
			rejected++
		}
	}
	require.Equal(t, 1, admitted)
	require.Equal(t, 1, rejected)
}
