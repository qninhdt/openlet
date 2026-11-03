//go:build integration

package workspace

import (
	"context"
	"crypto/sha256"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/testcontainers/testcontainers-go"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	localfixture "github.com/qninhdt/openlet/apps/workspace/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"os"
)

func setupGraph(t *testing.T, store *Store) testcontainers.Container {
	t.Helper()
	graph, _, server := testfixture.SpiceDB(t, localfixture.Path("packages", "contracts", "authz", "schema.zed"))
	data, err := os.ReadFile(localfixture.Path("packages", "contracts", "authz", "roles.json"))
	require.NoError(t, err)
	policy, err := authz.ParseRolePolicy(data)
	require.NoError(t, err)
	require.NoError(t, authz.InitializeRolePolicy(t.Context(), graph, policy))
	store.Graph = graph
	return server
}

func syncGraph(t *testing.T, store *Store, id uuid.UUID) {
	t.Helper()
	require.NoError(t, store.RebuildWorkspaceRelationships(t.Context(), store.Graph, id))
}

func TestIntegrationWorkspaceCollaboration(t *testing.T) {
	db := postgres(t)
	store := Store{DB: db, MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	setupGraph(t, &store)
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
	require.NoError(t, store.Activate(ctx, mapping(created.ID)))
	ws := created.ID
	syncGraph(t, &store, ws)
	_, err = store.Authorize(ctx, ws, member, authz.WorkspaceRead)
	require.EqualError(t, err, "NOT_FOUND")
	invitation, token, err := store.Invite(ctx, ws, owner, "member@example.com", "editor")
	require.NoError(t, err)
	require.NotEmpty(t, invitation.ID)
	require.NotEmpty(t, token)
	_, err = store.AcceptInvite(ctx, member, sha256.Sum256([]byte(token)), []string{"other@example.com"}, MutationReceipt{})
	require.EqualError(t, err, "INVITATION_EMAIL_MISMATCH")
	accepted, err := store.AcceptInvite(ctx, member, sha256.Sum256([]byte(token)), []string{"MEMBER@example.com"}, MutationReceipt{})
	require.NoError(t, err)
	require.Equal(t, ws, accepted)
	syncGraph(t, &store, ws)
	_, err = store.AcceptInvite(ctx, member, sha256.Sum256([]byte(token)), []string{"member@example.com"}, MutationReceipt{})
	require.NoError(t, err)
	_, err = store.Authorize(ctx, ws, member, authz.MemberRead)
	require.NoError(t, err)
	current, err := store.Authorize(ctx, ws, owner, authz.WorkspaceTransfer)
	require.NoError(t, err)
	require.EqualError(t, store.ChangeMember(ctx, ws, owner, owner, "", true, current.Revision, MutationReceipt{}), "OWNER_TRANSFER_REQUIRED")
	transferred, err := store.Update(ctx, ws, owner, current.Revision, UpdateInput{OwnerID: &member}, MutationReceipt{})
	require.NoError(t, err)
	require.NotEqual(t, current.Revision, transferred.Revision)
	syncGraph(t, &store, ws)
	_, err = store.Authorize(ctx, ws, owner, authz.WorkspaceTransfer)
	require.EqualError(t, err, "FORBIDDEN")
	current, err = store.Authorize(ctx, ws, member, authz.WorkspaceTransfer)
	require.NoError(t, err)
	name := "Renamed"
	renamed, err := store.Update(ctx, ws, member, current.Revision, UpdateInput{Name: &name}, MutationReceipt{})
	require.NoError(t, err)
	_, err = store.Update(ctx, ws, member, current.Revision, UpdateInput{Name: &name}, MutationReceipt{})
	require.EqualError(t, err, "REVISION_MISMATCH")
	require.NoError(t, store.ChangeMember(ctx, ws, member, owner, "", true, renamed.Revision, MutationReceipt{}))
	current, err = store.Get(ctx, ws, member)
	require.NoError(t, err)
	_, err = store.AcceptInvite(ctx, owner, sha256.Sum256([]byte(token)), []string{"member@example.com"}, MutationReceipt{})
	require.EqualError(t, err, "INVITATION_INVALID")
	deletion := DeleteInput{ActorID: member, WorkspaceID: ws, Revision: current.Revision}
	begun, err := store.BeginDeletion(ctx, deletion)
	require.NoError(t, err)
	repeated, err := store.BeginDeletion(ctx, deletion)
	require.NoError(t, err)
	require.Equal(t, begun.ID, repeated.ID)
	require.Equal(t, "deleting", repeated.Status)
	_, err = store.Authorize(ctx, ws, member, authz.WorkspaceTransfer)
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

func postgres(t *testing.T) *pgxpool.Pool {
	t.Helper()
	return testfixture.Postgres(t, localfixture.Path("apps", "workspace", "migrations", "0001_initial.sql"))
}

func TestIntegrationStorageReservationSurvivesConcurrentRetryAndRejectsRebinding(t *testing.T) {
	ctx := t.Context()
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024}
	actor := uuid.New()
	input := CreateInput{ActorID: actor, Key: uuid.New(), Name: "Stable storage"}
	admission, err := store.EnsureWorkspace(ctx, input)
	require.NoError(t, err)
	id := admission.ID
	type reservation struct {
		storage Storage
		err     error
	}
	results := make(chan reservation, 8)
	var workers sync.WaitGroup
	for range 8 {
		workers.Go(func() {
			storage, err := store.ReserveStorage(ctx, id)
			results <- reservation{storage, err}
		})
	}
	workers.Wait()
	close(results)
	var reserved Storage
	for result := range results {
		require.NoError(t, result.err)
		if reserved.BucketID == uuid.Nil {
			reserved = result.storage
		}
		require.Equal(t, reserved, result.storage)
	}
	require.Equal(t, uuid.Version(7), reserved.BucketID.Version())
	require.Equal(t, uuid.Version(7), reserved.FilesystemID.Version())
	require.NotEqual(t, reserved.BucketID, reserved.FilesystemID)
	require.Equal(t, uuid.Nil, reserved.RootID, "root is returned by letfs after creation")
	owner, err := store.EnsureWorkspace(ctx, input)
	require.NoError(t, err)
	require.Equal(t, reserved.BucketID, *owner.BucketID)
	require.Equal(t, reserved.FilesystemID, *owner.FilesystemID)
	foreign := reserved
	foreign.RootID = uuid.New()
	foreign.BucketID = uuid.New()
	require.EqualError(t, store.Activate(ctx, foreign), "STATE_CONFLICT")
	foreign = reserved
	foreign.RootID = uuid.New()
	foreign.FilesystemID = uuid.New()
	require.EqualError(t, store.Activate(ctx, foreign), "STATE_CONFLICT")
	reserved.RootID = uuid.New()
	require.NoError(t, store.Activate(ctx, reserved))
	require.NoError(t, store.Activate(ctx, reserved))
	again, err := store.ReserveStorage(ctx, id)
	require.NoError(t, err)
	require.Equal(t, reserved, again)
	foreign = reserved
	foreign.RootID = uuid.New()
	require.EqualError(t, store.Activate(ctx, foreign), "STATE_CONFLICT")
	_, err = store.DB.Exec(ctx, `UPDATE workspaces SET status='deleting' WHERE id=$1`, id)
	require.NoError(t, err)
	_, err = store.ReserveStorage(ctx, id)
	require.EqualError(t, err, "STATE_CONFLICT")
	require.EqualError(t, store.Activate(ctx, reserved), "STATE_CONFLICT")
	require.NoError(t, store.CompleteDeletion(ctx, id))
	_, err = store.ReserveStorage(ctx, id)
	require.EqualError(t, err, "STATE_CONFLICT")
	value, err := store.Get(ctx, id, actor)
	require.NoError(t, err)
	require.Equal(t, reserved.BucketID, *value.BucketID, "deletion retains the late-create fence identity")
}

func TestIntegrationConcurrentInvitationsReturnOneToken(t *testing.T) {
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024, InviteTTL: time.Hour}
	setupGraph(t, &store)
	owner := uuid.Must(uuid.NewV7())
	provision, err := store.EnsureWorkspace(t.Context(), CreateInput{ActorID: owner, Key: uuid.Must(uuid.NewV7()), Name: "Team"})
	require.NoError(t, err)
	require.NoError(t, store.Activate(t.Context(), mapping(provision.ID)))
	syncGraph(t, &store, provision.ID)
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
			invitation, token, err := store.Invite(t.Context(), provision.ID, owner, " GUEST@EXAMPLE.COM ", "viewer")
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
	_, _, err = store.Invite(t.Context(), provision.ID, owner, "guest@example.com", "editor")
	require.EqualError(t, err, "INVITATION_CONFLICT")
	require.NoError(t, store.RevokeInvite(t.Context(), provision.ID, owner, id))
	next, token, err := store.Invite(t.Context(), provision.ID, owner, "guest@example.com", "viewer")
	require.NoError(t, err)
	require.NotEqual(t, id, next.ID)
	require.NotEmpty(t, token)
	_, err = store.DB.Exec(t.Context(), `UPDATE workspace_invitations SET expires_at=now()-interval '1 second' WHERE id=$1`, next.ID)
	require.NoError(t, err)
	renewed, token, err := store.Invite(t.Context(), provision.ID, owner, "guest@example.com", "viewer")
	require.NoError(t, err)
	require.NotEqual(t, next.ID, renewed.ID)
	guest := uuid.Must(uuid.NewV7())
	_, err = store.AcceptInvite(t.Context(), guest, sha256.Sum256([]byte(token)), []string{"guest@example.com"}, MutationReceipt{})
	require.NoError(t, err)
	current, err := store.Get(t.Context(), provision.ID, owner)
	require.NoError(t, err)
	require.NoError(t, store.ChangeMember(t.Context(), current.ID, owner, guest, "", true, current.Revision, MutationReceipt{}))
	_, err = store.AcceptInvite(t.Context(), guest, sha256.Sum256([]byte(token)), []string{"guest@example.com"}, MutationReceipt{})
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
		value Workspace
		err   error
	}
	results := make(chan result, 8)
	var workers sync.WaitGroup
	for range 8 {
		workers.Go(func() { value, err := store.EnsureWorkspace(ctx, in); results <- result{value, err} })
	}
	workers.Wait()
	close(results)
	var admitted Workspace
	for value := range results {
		require.NoError(t, value.err)
		if admitted.ID == uuid.Nil {
			admitted = value.value
		}
		require.Equal(t, admitted.ID, value.value.ID)
		require.Nil(t, value.value.BucketID)
	}
	saved, found, err := store.FindCreation(ctx, in)
	require.NoError(t, err)
	require.True(t, found)
	require.Equal(t, admitted.ID, saved.ID)
	require.NoError(t, store.PruneReceipts(ctx))
	var count int
	require.NoError(t, store.DB.QueryRow(ctx, `SELECT count(*) FROM idempotency_keys`).Scan(&count))
	require.Equal(t, 1, count)
	// The resource cannot become active until its owner-returned mapping is complete.
	require.EqualError(t, store.Activate(ctx, Storage{WorkspaceID: admitted.ID}), "VALIDATION")
	assigned := mapping(admitted.ID)
	require.NoError(t, store.Activate(ctx, assigned))
	pendingKey := uuid.New()
	_, err = store.DB.Exec(ctx, `INSERT INTO idempotency_keys(actor_id,request_key,request_hash,workspace_id) VALUES($1,$2,'pending-mutation',$3)`, in.ActorID, pendingKey, admitted.ID)
	require.NoError(t, err)
	require.NoError(t, store.CompleteCreation(ctx, in))
	var pending bool
	require.NoError(t, store.DB.QueryRow(ctx, `SELECT expires_at IS NULL FROM idempotency_keys WHERE request_key=$1`, pendingKey).Scan(&pending))
	require.True(t, pending, "creation completion cannot expire an unrelated in-flight mutation")
	var expiresInWindow bool
	require.NoError(t, store.DB.QueryRow(ctx, `SELECT expires_at BETWEEN now()+interval '23 hours 59 minutes' AND now()+interval '24 hours 1 minute' FROM idempotency_keys WHERE request_key=$1`, in.Key).Scan(&expiresInWindow))
	require.True(t, expiresInWindow)
	require.NoError(t, store.Activate(ctx, assigned))
	different := assigned
	different.BucketID = uuid.New()
	require.EqualError(t, store.Activate(ctx, different), "STATE_CONFLICT")
	// Completed receipts release their keys after the documented TTL.
	_, err = store.DB.Exec(ctx, `UPDATE idempotency_keys SET expires_at=now()-interval '1 hour'`)
	require.NoError(t, err)
	require.NoError(t, store.PruneReceipts(ctx))
	next, err := store.EnsureWorkspace(ctx, in)
	require.NoError(t, err)
	require.NotEqual(t, admitted.ID, next.ID)
}

func TestIntegrationInitialWorkspaceReceiptRemainsRecoverable(t *testing.T) {
	store := Store{DB: postgres(t), MaxWorkspaces: 10, MaxMembers: 10, QuotaLimit: 1024}
	ctx := t.Context()
	actor := uuid.New()
	initial := CreateInput{ActorID: actor, Key: actor, Name: "My workspace"}
	service := Service{Store: &store}
	service.StartInitial = func(ctx context.Context, in CreateInput) (Workspace, error) {
		return store.EnsureWorkspace(ctx, in)
	}

	_, err := service.Create(ctx, initial)
	require.EqualError(t, err, "VALIDATION", "the account identity is reserved for initial-workspace admission")
	admitted, completed, err := service.EnsureInitial(ctx, initial)
	require.NoError(t, err)
	require.False(t, completed)
	require.NoError(t, store.Activate(ctx, mapping(admitted.ID)))
	require.NoError(t, store.CompleteCreation(ctx, initial))

	ordinary := CreateInput{ActorID: uuid.New(), Key: uuid.New(), Name: "Ordinary workspace"}
	ordinaryWorkspace, err := store.EnsureWorkspace(ctx, ordinary)
	require.NoError(t, err)
	require.NoError(t, store.Activate(ctx, mapping(ordinaryWorkspace.ID)))
	require.NoError(t, store.CompleteCreation(ctx, ordinary))
	_, err = store.DB.Exec(ctx, `UPDATE idempotency_keys SET expires_at=now()-interval '1 hour' WHERE actor_id=$1 AND request_key=$2`, ordinary.ActorID, ordinary.Key)
	require.NoError(t, err)
	require.NoError(t, store.PruneReceipts(ctx))

	service.StartInitial = func(context.Context, CreateInput) (Workspace, error) {
		t.Fatal("durable initial receipt must prevent a duplicate workflow start")
		return Workspace{}, nil
	}
	recovered, completed, err := service.EnsureInitial(ctx, initial)
	require.NoError(t, err)
	require.True(t, completed)
	require.Equal(t, admitted.ID, recovered.ID)
	_, found, err := store.FindCreation(ctx, ordinary)
	require.NoError(t, err)
	require.False(t, found)
}

func TestIntegrationFailedProvisioningCanBeDeleted(t *testing.T) {
	store := Store{DB: postgres(t), MaxWorkspaces: 1, MaxMembers: 10, QuotaLimit: 1024}
	setupGraph(t, &store)
	ctx := t.Context()
	actor := uuid.New()
	admitted, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: actor, Key: uuid.New(), Name: "Failed"})
	require.NoError(t, err)
	require.NoError(t, store.Fail(ctx, admitted.ID))
	syncGraph(t, &store, admitted.ID)
	failed, err := store.Get(ctx, admitted.ID, actor)
	require.NoError(t, err)
	require.Equal(t, "failed", failed.Status)
	require.NotNil(t, failed.ErrorCode)
	_, err = store.BeginDeletion(ctx, DeleteInput{ActorID: actor, WorkspaceID: failed.ID, Revision: failed.Revision})
	require.NoError(t, err)
	require.NoError(t, store.CompleteDeletion(ctx, failed.ID))
	next, err := store.EnsureWorkspace(ctx, CreateInput{ActorID: actor, Key: uuid.New(), Name: "Fresh"})
	require.NoError(t, err)
	require.NotEqual(t, failed.ID, next.ID)
}
