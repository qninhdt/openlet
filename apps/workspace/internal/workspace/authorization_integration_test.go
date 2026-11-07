//go:build integration

package workspace

import (
	"crypto/sha256"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/stretchr/testify/require"
)

func TestIntegrationMembershipIsolationAndInvitationReplay(t *testing.T) {
	store := Store{DB: postgres(t), MaxMembers: 10, InviteTTL: time.Hour}
	setupGraph(t, &store)
	service := Service{Store: &store}
	ctx := t.Context()
	owner, admin, member := uuid.New(), uuid.New(), uuid.New()
	in := creation(owner)
	_, err := service.SaveWorkspace(ctx, in)
	require.NoError(t, err)
	scopes := map[uuid.UUID]uuid.UUID{}
	for actor, role := range map[uuid.UUID]string{admin: "admin", member: "member"} {
		scopes[actor] = uuid.New()
		_, err = service.ApplyMembership(ctx, Mutation{Kind: "add", Key: uuid.New(), WorkspaceID: in.ID, ActorID: owner, TargetID: actor, Role: role, PersonalScopeID: scopes[actor]})
		require.NoError(t, err)
	}
	check := func(actor uuid.UUID, action authz.Action, kind string, id uuid.UUID, want bool) {
		t.Helper()
		got, err := authz.Check(ctx, store.Graph, actor.String(), action, authz.Resource{Type: kind, ID: id.String()})
		require.NoError(t, err)
		require.Equal(t, want, got)
	}
	check(admin, authz.WorkspaceManageMembers, "workspace", in.ID, true)
	check(admin, authz.WorkspaceDelete, "workspace", in.ID, false)
	check(admin, authz.ScopeManageAccess, "scope", in.SharedScopeID, true)
	check(member, authz.ScopeWrite, "scope", in.SharedScopeID, true)
	check(admin, authz.ScopeReadContent, "scope", scopes[member], false)
	check(owner, authz.ScopeReadContent, "scope", scopes[member], false)
	check(member, authz.ScopeManageAccess, "scope", scopes[member], true)
	check(member, authz.WorkspaceManageMembers, "workspace", in.ID, false)
	require.EqualError(t, service.ChangeMember(ctx, in.ID, admin, owner, "member", false), "FORBIDDEN")
	require.EqualError(t, service.ChangeMember(ctx, in.ID, owner, owner, "", true), "FORBIDDEN")
	invitation, token, err := store.Invite(ctx, in.ID, owner, "invite@example.com", "member")
	require.NoError(t, err)
	require.NotEmpty(t, invitation.ID)
	hash := sha256.Sum256([]byte(token))
	joined := uuid.New()
	_, _, err = store.AdmitInvitation(ctx, joined, hash, []string{"wrong@example.com"})
	require.EqualError(t, err, "INVITATION_EMAIL_MISMATCH")
	ws, role, err := store.AdmitInvitation(ctx, joined, hash, []string{"INVITE@example.com"})
	require.NoError(t, err)
	require.Equal(t, in.ID, ws)
	personal := uuid.New()
	_, err = service.ApplyMembership(ctx, Mutation{Kind: "join", Key: uuid.New(), WorkspaceID: ws, ActorID: joined, TargetID: joined, Role: role, PersonalScopeID: personal, InvitationHash: hash})
	require.NoError(t, err)
	removal := Mutation{Kind: "member", Key: uuid.New(), WorkspaceID: ws, ActorID: joined, TargetID: joined, Remove: true}
	_, err = service.ApplyMembership(ctx, removal)
	require.NoError(t, err)
	check(joined, authz.ScopeReadContent, "scope", in.SharedScopeID, false)
	check(joined, authz.ScopeManageAccess, "scope", personal, false)
	retained, err := store.Member(ctx, ws, joined)
	require.NoError(t, err)
	require.Equal(t, personal, retained.PersonalScopeID)
	require.Equal(t, "inactive", retained.Status)
	_, _, err = store.AdmitInvitation(ctx, joined, hash, []string{"invite@example.com"})
	require.EqualError(t, err, "INVITATION_ALREADY_USED")
	_, err = service.ApplyMembership(ctx, Mutation{Kind: "add", Key: uuid.New(), WorkspaceID: ws, ActorID: owner, TargetID: joined, Role: "member", PersonalScopeID: personal, ExistingScope: true})
	require.NoError(t, err)
	check(joined, authz.ScopeManageAccess, "scope", personal, true)
}
