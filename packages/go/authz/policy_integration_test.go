//go:build integration

package authz

import (
	"context"
	"fmt"
	"os"
	"slices"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/stretchr/testify/require"
)

func TestIntegrationRepositoryPolicyInitializationAndActions(t *testing.T) {
	client, address, server := graph(t)
	independent := connect(t, address)
	ctx := t.Context()
	data, err := os.ReadFile("../../contracts/authz/roles.json")
	require.NoError(t, err)
	policy, err := ParseRolePolicy(data)
	require.NoError(t, err)
	require.ErrorIs(t, VerifyRolePolicy(ctx, client, policy), ErrPolicyMismatch)
	require.NoError(t, InitializeRolePolicy(ctx, client, policy))
	require.NoError(t, InitializeRolePolicy(ctx, client, policy))
	require.NoError(t, VerifyRolePolicy(ctx, independent, policy))

	for _, role := range []string{"owner", "editor", "viewer"} {
		write(t, client,
			touch("role_grant", "team-"+role, "role", "role", role),
			touch("role_grant", "team-"+role, "member", "user", role),
			touch("workspace", "team", "grant", "role_grant", "team-"+role))
	}
	write(t, client,
		touch("workspace", "team", "enabled", "user", "*"),
		touch("filesystem", "drive", "workspace", "workspace", "team"),
		touch("quota_bucket", "bucket", "workspace", "workspace", "team"),
		touch("filesystem", "foreign", "workspace", "workspace", "other"))
	read := []Action{WorkspaceRead, MemberRead, MemberLeave, NodeList, NodeRead, NodeResolve, ContentRead, TrashRead, CopyRead, ProcessingRead, Search, Archive, BucketRead}
	edit := []Action{NodeCreate, NodeUpdate, NodeTrash, ContentWrite, TrashRestore, UploadCreate, UploadRead, UploadSign, UploadComplete, UploadAbort, CopyCreate, ProcessingRun}
	manage := []Action{WorkspaceUpdate, WorkspaceDelete, WorkspaceTransfer, MemberManage, InvitationRead, InvitationCreate, InvitationRevoke, TrashPurge, CopyInspectAny, BucketAdmin}
	for _, action := range append(append(slices.Clone(read), edit...), manage...) {
		resource := Resource{Type: "filesystem", ID: "drive"}
		if action.Valid("workspace") {
			resource = Resource{Type: "workspace", ID: "team"}
		} else if action.Valid("quota_bucket") {
			resource = Resource{Type: "quota_bucket", ID: "bucket"}
		}
		for _, role := range []string{"owner", "editor", "viewer"} {
			allowed, err := Check(ctx, independent, role, action, resource)
			require.NoError(t, err)
			want := role == "owner" || slices.Contains(read, action) || (role == "editor" && slices.Contains(edit, action))
			require.Equal(t, want, allowed, "%s %s", role, action)
		}
	}
	allowed, err := Check(ctx, independent, "owner", NodeRead, Resource{Type: "filesystem", ID: "foreign"})
	require.NoError(t, err)
	require.False(t, allowed)

	// Startup check detects drift without granting access; the fenced initializer repairs policy only.
	write(t, client,
		touch("role", "viewer", "node_create", "user", "*"),
		remove("role", "editor", "content_write", "user", "*"),
		touch("role", "obsolete", "node_read", "user", "*"))
	require.ErrorIs(t, VerifyRolePolicy(ctx, client, policy), ErrPolicyMismatch)
	allowed, err = Check(ctx, independent, "editor", ContentWrite, Resource{Type: "filesystem", ID: "drive"})
	require.NoError(t, err)
	require.False(t, allowed, "verification cannot silently repair policy")
	require.NoError(t, InitializeRolePolicy(ctx, client, policy))
	require.NoError(t, VerifyRolePolicy(ctx, independent, policy))
	allowed, err = Check(ctx, independent, "viewer", NodeCreate, Resource{Type: "filesystem", ID: "drive"})
	require.NoError(t, err)
	require.False(t, allowed, "unexpected capabilities are removed")
	allowed, err = Check(ctx, independent, "editor", ContentWrite, Resource{Type: "filesystem", ID: "drive"})
	require.NoError(t, err)
	require.True(t, allowed, "business grants/bindings survive policy reconciliation")
	bulk, err := BulkCheck(ctx, independent, "viewer", NodeRead, []Resource{{Type: "filesystem", ID: "drive"}, {Type: "filesystem", ID: "foreign"}})
	require.NoError(t, err)
	require.Equal(t, []bool{true, false}, bulk)

	canceled, cancel := context.WithCancel(ctx)
	cancel()
	require.Error(t, InitializeRolePolicy(canceled, client, policy))
	_, err = client.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{
		remove("workspace", "team", "enabled", "user", "*"),
	}})
	require.NoError(t, err)
	allowed, err = Check(ctx, independent, "owner", NodeRead, Resource{Type: "filesystem", ID: "drive"})
	require.NoError(t, err)
	require.False(t, allowed, "workspace lifecycle disables inherited file access")
	allowed, err = Check(ctx, independent, "owner", WorkspaceRead, Resource{Type: "workspace", ID: "team"})
	require.NoError(t, err)
	require.True(t, allowed, "nonactive status remains readable")

	_, err = client.DeleteRelationships(ctx, &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "role"}})
	require.NoError(t, err)
	var oversized []*v1.RelationshipUpdate
	for i := range 928 {
		oversized = append(oversized, touch("role", fmt.Sprintf("obsolete-%d", i), "node_read", "user", "*"))
	}
	write(t, client, oversized...)
	require.ErrorIs(t, InitializeRolePolicy(ctx, client, policy), ErrPolicyMismatch, "oversized drift must fail before exceeding the atomic update limit")
	require.NoError(t, server.Stop(ctx, nil))
	deadline, cancel := context.WithTimeout(ctx, time.Second)
	defer cancel()
	require.Error(t, VerifyRolePolicy(deadline, independent, policy), "outage cannot report policy ready")
}
