//go:build integration

package workspace

import (
	"context"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/testcontainers/testcontainers-go"
	"github.com/testcontainers/testcontainers-go/wait"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func TestIntegrationWorkspaceCollaboration(t *testing.T) {
	db := postgres(t)
	store := Store{DB: db, MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	ctx := t.Context()
	owner, member := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	input := CreateInput{ActorID: owner, Key: uuid.Must(uuid.NewV7()), Name: "Team"}
	created, err := store.EnsureWorkspace(ctx, input, "")
	require.NoError(t, err)
	again, err := store.EnsureWorkspace(ctx, input, "")
	require.NoError(t, err)
	require.Equal(t, created, again)
	changed := input
	changed.Name = "Different"
	_, err = store.EnsureWorkspace(ctx, changed, "")
	require.EqualError(t, err, "IDEMPOTENCY_CONFLICT")
	require.NoError(t, store.Activate(ctx, mapping(created.Workspace.ID)))
	ws := created.Workspace.ID
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
	current, err := store.Authorize(ctx, ws, owner, "owner")
	require.NoError(t, err)
	require.EqualError(t, store.ChangeMember(ctx, ws, owner, owner, "", true, current.Revision), "OWNER_TRANSFER_REQUIRED")
	transferred, err := store.Update(ctx, ws, owner, current.Revision, UpdateInput{OwnerID: &member})
	require.NoError(t, err)
	require.NotEqual(t, current.Revision, transferred.Revision)
	_, err = store.Authorize(ctx, ws, owner, "owner")
	require.EqualError(t, err, "FORBIDDEN")
	current, err = store.Authorize(ctx, ws, member, "owner")
	require.NoError(t, err)
	name := "Renamed"
	renamed, err := store.Update(ctx, ws, member, current.Revision, UpdateInput{Name: &name})
	require.NoError(t, err)
	_, err = store.Update(ctx, ws, member, current.Revision, UpdateInput{Name: &name})
	require.EqualError(t, err, "REVISION_MISMATCH")
	require.NoError(t, store.ChangeMember(ctx, ws, member, owner, "", true, renamed.Revision))
	current, err = store.Get(ctx, ws, member)
	require.NoError(t, err)
	_, err = store.AcceptInvite(ctx, owner, token, []string{"member@example.com"})
	require.EqualError(t, err, "INVITATION_INVALID")
	deletion := DeleteInput{ActorID: member, WorkspaceID: ws, Revision: current.Revision}
	begun, err := store.BeginDeletion(ctx, deletion)
	require.NoError(t, err)
	repeated, err := store.BeginDeletion(ctx, deletion)
	require.NoError(t, err)
	require.Equal(t, begun.ID, repeated.ID)
	pending, err := store.Pending(ctx)
	require.NoError(t, err)
	require.Len(t, pending, 1)
	require.Equal(t, "deleting", pending[0].Status)
	_, err = store.Authorize(ctx, ws, member, "owner")
	require.EqualError(t, err, "WORKSPACE_DELETING")
	require.NoError(t, store.CompleteDeletion(ctx, ws))
	require.NoError(t, store.CompleteDeletion(ctx, ws))
	tombstone, err := store.Get(ctx, ws, member)
	require.NoError(t, err)
	require.Equal(t, "deleted", tombstone.Status)
	_, err = store.Get(ctx, ws, owner)
	require.EqualError(t, err, "NOT_FOUND")
	deleted, err := store.BeginDeletion(ctx, deletion)
	require.NoError(t, err)
	require.Equal(t, "deleted", deleted.Status)
}

func TestIntegrationConcurrentWorkspaceLimit(t *testing.T) {
	db := postgres(t)
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
			}, "")
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

func postgres(t *testing.T) *pgxpool.Pool {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), 2*time.Minute)
	defer cancel()
	baseline, err := filepath.Abs("../../migrations/0001_initial.sql")
	require.NoError(t, err)
	container, err := testcontainers.GenericContainer(ctx, testcontainers.GenericContainerRequest{
		ContainerRequest: testcontainers.ContainerRequest{
			Image:        "postgres:18.6-trixie@sha256:74935e72241653ca55e0414067e6d8763aceb8a810eb51b452253ec3dcfc4336",
			Env:          map[string]string{"POSTGRES_USER": "owner", "POSTGRES_DB": "application", "POSTGRES_PASSWORD": "isolated-test-password"},
			ExposedPorts: []string{"5432/tcp"},
			Files:        []testcontainers.ContainerFile{{HostFilePath: baseline, ContainerFilePath: "/docker-entrypoint-initdb.d/10-baseline.sql", FileMode: 0o444}},
			WaitingFor:   wait.ForLog("database system is ready to accept connections").WithOccurrence(2).WithStartupTimeout(time.Minute),
		}, Started: true,
	})
	if container != nil {
		testcontainers.CleanupContainer(t, container)
	}
	require.NoError(t, err)
	host, err := container.Host(ctx)
	require.NoError(t, err)
	port, err := container.MappedPort(ctx, "5432/tcp")
	require.NoError(t, err)
	db, err := pgxpool.New(ctx, "postgres://owner:isolated-test-password@"+host+":"+port.Port()+"/application?sslmode=disable")
	require.NoError(t, err)
	t.Cleanup(db.Close)
	require.NoError(t, db.Ping(ctx))
	return db
}

func TestIntegrationConcurrentInvitationsReturnOneToken(t *testing.T) {
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	owner := uuid.Must(uuid.NewV7())
	provision, err := store.EnsureWorkspace(t.Context(), CreateInput{ActorID: owner, Key: uuid.Must(uuid.NewV7()), Name: "Team"}, "")
	require.NoError(t, err)
	require.NoError(t, store.Activate(t.Context(), mapping(provision.Workspace.ID)))
	type result struct {
		invitation Invitation
		token      string
		err        error
	}
	results := make(chan result, 8)
	start := make(chan struct{})
	var workers sync.WaitGroup
	for range 8 {
		workers.Go(func() {
			<-start
			invitation, token, err := store.Invite(t.Context(), provision.Workspace.ID, owner, " GUEST@EXAMPLE.COM ", "viewer")
			results <- result{invitation, token, err}
		})
	}
	close(start)
	workers.Wait()
	close(results)
	var id uuid.UUID
	tokens := 0
	for value := range results {
		require.NoError(t, value.err)
		if id == uuid.Nil {
			id = value.invitation.ID
		}
		require.Equal(t, id, value.invitation.ID)
		if value.token != "" {
			tokens++
		}
	}
	require.Equal(t, 1, tokens)
	_, _, err = store.Invite(t.Context(), provision.Workspace.ID, owner, "guest@example.com", "editor")
	require.EqualError(t, err, "INVITATION_CONFLICT")
	require.NoError(t, store.RevokeInvite(t.Context(), provision.Workspace.ID, owner, id))
	next, token, err := store.Invite(t.Context(), provision.Workspace.ID, owner, "guest@example.com", "viewer")
	require.NoError(t, err)
	require.NotEqual(t, id, next.ID)
	require.NotEmpty(t, token)
	_, err = store.DB.Exec(t.Context(), `UPDATE workspace_invitations SET expires_at=now()-interval '1 second' WHERE id=$1`, next.ID)
	require.NoError(t, err)
	renewed, token, err := store.Invite(t.Context(), provision.Workspace.ID, owner, "guest@example.com", "viewer")
	require.NoError(t, err)
	require.NotEqual(t, next.ID, renewed.ID)
	guest := uuid.Must(uuid.NewV7())
	_, err = store.AcceptInvite(t.Context(), guest, token, []string{"guest@example.com"})
	require.NoError(t, err)
	current, err := store.Get(t.Context(), provision.Workspace.ID, owner)
	require.NoError(t, err)
	require.NoError(t, store.ChangeMember(t.Context(), current.ID, owner, guest, "", true, current.Revision))
	_, err = store.AcceptInvite(t.Context(), guest, token, []string{"guest@example.com"})
	require.EqualError(t, err, "INVITATION_ALREADY_USED")
}

func mapping(workspace uuid.UUID) Storage {
	return Storage{WorkspaceID: workspace, BucketID: uuid.Must(uuid.NewV7()), FilesystemID: uuid.Must(uuid.NewV7()), RootID: uuid.Must(uuid.NewV7()), LimitBytes: "1024"}
}
func TestIntegrationWorkspaceReceiptAdmissionAndExpiry(t *testing.T) {
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024}
	ctx := t.Context()
	in := CreateInput{ActorID: uuid.New(), Key: uuid.New(), Name: "Same request"}
	type result struct {
		value Provision
		err   error
	}
	results := make(chan result, 8)
	var workers sync.WaitGroup
	for range 8 {
		workers.Go(func() { value, err := store.EnsureWorkspace(ctx, in, ""); results <- result{value, err} })
	}
	workers.Wait()
	close(results)
	var admitted Provision
	for value := range results {
		require.NoError(t, value.err)
		if admitted.Workspace.ID == uuid.Nil {
			admitted = value.value
		}
		require.Equal(t, admitted.Workspace.ID, value.value.Workspace.ID)
		require.Equal(t, admitted.WorkflowID, value.value.WorkflowID)
		require.Nil(t, value.value.Workspace.BucketID)
	}
	pending, err := store.Pending(ctx)
	require.NoError(t, err)
	require.Len(t, pending, 1)
	require.Equal(t, in, pending[0].Provision.Input)
	require.Equal(t, admitted.WorkflowID, pending[0].Provision.WorkflowID)
	require.NoError(t, store.PruneReceipts(ctx))
	var count int
	require.NoError(t, store.DB.QueryRow(ctx, `SELECT count(*) FROM idempotency_keys`).Scan(&count))
	require.Equal(t, 1, count)
	// The resource cannot become active until its owner-returned mapping is complete.
	require.EqualError(t, store.Activate(ctx, Storage{WorkspaceID: admitted.Workspace.ID}), "VALIDATION")
	assigned := mapping(admitted.Workspace.ID)
	require.NoError(t, store.Activate(ctx, assigned))
	unreleased, err := store.UnreleasedProvisioning(ctx)
	require.NoError(t, err)
	require.Equal(t, []Storage{assigned}, unreleased)
	require.NoError(t, store.CompleteCreation(ctx, assigned.WorkspaceID))
	unreleased, err = store.UnreleasedProvisioning(ctx)
	require.NoError(t, err)
	require.Empty(t, unreleased)
	var lifetime float64
	require.NoError(t, store.DB.QueryRow(ctx, `SELECT extract(epoch FROM expires_at-completed_at) FROM idempotency_keys`).Scan(&lifetime))
	require.Equal(t, 86400.0, lifetime)
	require.NoError(t, store.Activate(ctx, assigned))
	different := assigned
	different.BucketID = uuid.New()
	require.EqualError(t, store.Activate(ctx, different), "STATE_CONFLICT")
	// An expired client key may admit new work, while the old workflow identity cannot.
	_, err = store.DB.Exec(ctx, `UPDATE idempotency_keys SET completed_at=now()-interval '25 hours',expires_at=now()-interval '1 hour'`)
	require.NoError(t, err)
	require.NoError(t, store.PruneReceipts(ctx))
	old, err := store.EnsureWorkspace(ctx, in, admitted.WorkflowID)
	require.NoError(t, err)
	require.Equal(t, admitted.Workspace.ID, old.Workspace.ID)
	next, err := store.EnsureWorkspace(ctx, in, "")
	require.NoError(t, err)
	require.NotEqual(t, admitted.Workspace.ID, next.Workspace.ID)
}

func TestIntegrationFailedProvisioningCanBeDeleted(t *testing.T) {
	store := Store{DB: postgres(t), MaxWorkspaces: 1, MaxMembers: 10, QuotaLimit: 1024}
	ctx := t.Context()
	actor := uuid.New()
	admitted, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: actor, Key: uuid.New(), Name: "Failed"}, "")
	require.NoError(t, err)
	require.NoError(t, store.Fail(ctx, admitted.Workspace.ID))
	failed, err := store.Get(ctx, admitted.Workspace.ID, actor)
	require.NoError(t, err)
	require.Equal(t, "failed", failed.Status)
	require.NotNil(t, failed.ErrorCode)
	_, err = store.BeginDeletion(ctx, DeleteInput{ActorID: actor, WorkspaceID: failed.ID, Revision: failed.Revision})
	require.NoError(t, err)
	require.NoError(t, store.CompleteDeletion(ctx, failed.ID))
	next, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: actor, Key: uuid.New(), Name: "Fresh"}, "")
	require.NoError(t, err)
	require.NotEqual(t, failed.ID, next.Workspace.ID)
}
