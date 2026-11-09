//go:build integration

package workspace

import (
	"context"
	"github.com/qninhdt/openlet/packages/go/identity"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/stretchr/testify/require"
)

func TestIntegrationMembershipUsesOneConnection(t *testing.T) {
	db := postgres(t)
	config := db.Config()
	config.MaxConns, config.MinConns = 1, 0
	pool, err := pgxpool.NewWithConfig(t.Context(), config)
	require.NoError(t, err)
	t.Cleanup(pool.Close)
	store := Store{DB: pool, MaxMembers: 10}
	in := creation(uuid.New())
	_, err = store.SaveWorkspace(t.Context(), in)
	require.NoError(t, err)
	ctx, cancel := context.WithTimeout(t.Context(), 2*time.Second)
	defer cancel()
	mutation := Mutation{Kind: "add", Key: uuid.New(), WorkspaceID: in.ID, ActorID: in.Input.ActorID, TargetID: uuid.New(), Role: "member", PersonalScopeID: uuid.New()}
	require.NoError(t, store.applyMembership(ctx, mutation))
	require.NoError(t, store.applyMembership(ctx, mutation), "same command is retry-safe")
	mutation.Role = "admin"
	require.EqualError(t, store.applyMembership(ctx, mutation), "IDEMPOTENCY_CONFLICT")
}

func TestIntegrationRoleChangePreservesPersonalScopeGrants(t *testing.T) {
	store := Store{DB: postgres(t), MaxMembers: 10}
	setupGraph(t, &store)
	service := Service{Store: &store}
	ctx := t.Context()
	in := creation(uuid.New())
	_, err := service.SaveWorkspace(ctx, in)
	require.NoError(t, err)
	member, personal := uuid.New(), uuid.New()
	_, err = service.ApplyMembership(ctx, Mutation{Kind: "add", Key: uuid.New(), WorkspaceID: in.ID, ActorID: in.Input.ActorID, TargetID: member, Role: "member", PersonalScopeID: personal})
	require.NoError(t, err)
	_, err = service.UpdateScopeAccess(ctx, Mutation{TargetKind: identity.User, WorkspaceID: in.ID, ActorID: member, ScopeID: personal, TargetID: member, ScopeRole: "manager", Revoke: true})
	require.NoError(t, err)
	mutation := Mutation{Kind: "member", Key: uuid.New(), WorkspaceID: in.ID, ActorID: in.Input.ActorID, TargetID: member, Role: "admin"}
	for range 2 {
		_, err = service.ApplyMembership(ctx, mutation)
		require.NoError(t, err)
		allowed, err := authz.Check(ctx, store.Graph, identity.Actor{Kind: identity.User, ID: member}, authz.WorkspaceManageMembers, authz.Resource{Type: "workspace", ID: in.ID.String()})
		require.NoError(t, err)
		require.True(t, allowed)
		allowed, err = authz.Check(ctx, store.Graph, identity.Actor{Kind: identity.User, ID: member}, authz.ScopeManageAccess, authz.Resource{Type: "scope", ID: personal.String()})
		require.NoError(t, err)
		require.False(t, allowed, "a role change or its retry must not restore a revoked personal grant")
	}
}
