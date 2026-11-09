//go:build integration

package filesystem

import (
	"github.com/qninhdt/openlet/packages/go/apperr"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationDirectCopyReplaysCompletedNodeAndRetainsGuards(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, MaxCopyNodes: 64, InlineLimit: 64, MaxFileBytes: 64, MaxOutstanding: 10, MaxCleanupBacklog: 10}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, Service: "gateway", Gateway: true, ActorID: actor})
	fs, scope := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 1000})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{scope}, true, true)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", scope, actor, authz.ScopeWrite)
	content := []byte{0, 255, 13, 10}
	source, err := s.CreateNode(ctx, scope, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "source.bin", File: &InlineFile{Content: content, MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	input := CreateCopy{SourceID: source.ID, ParentID: *scopes[0].RootID, Name: "copy.bin", Revision: &source.Revision}
	invalid := input
	invalid.Revision = nil
	_, err = s.CopyNode(ctx, scope, uuid.New(), invalid)
	require.Equal(t, "PRECONDITION_REQUIRED", reason(err))
	key := uuid.New()
	copied, err := s.CopyNode(ctx, scope, key, input)
	require.NoError(t, err)
	require.NotEqual(t, source.ID, copied.ID)
	require.Equal(t, scope, copied.ScopeID)
	var saved []byte
	require.NoError(t, db.QueryRow(ctx, `SELECT inline_bytes FROM files WHERE node_id=$1`, copied.ID).Scan(&saved))
	require.Equal(t, content, saved)
	var used, count int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes,node_count FROM filesystems WHERE id=$1`, fs).Scan(&used, &count))
	require.EqualValues(t, 8, used)
	require.EqualValues(t, 3, count)
	replay, err := s.CopyNode(ctx, scope, key, input)
	require.NoError(t, err)
	require.Equal(t, copied, replay)
	changed := input
	changed.Name = "changed"
	_, err = s.CopyNode(ctx, scope, key, changed)
	require.Equal(t, "IDEMPOTENCY_CONFLICT", reason(err))
	updated, err := s.ReplaceContent(ctx, scope, Locator{NodeID: &source.ID}, &source.Revision, []byte("changed"), "application/octet-stream")
	require.NoError(t, err)
	_, err = s.CopyNode(ctx, scope, uuid.New(), input)
	require.Equal(t, "REVISION_MISMATCH", reason(err))
	_, err = s.TrashNode(ctx, scope, Locator{NodeID: &source.ID}, &updated.Revision, false)
	require.NoError(t, err)
	replay, err = s.CopyNode(ctx, scope, key, input)
	require.NoError(t, err)
	require.Equal(t, copied, replay)
	_, err = s.CopyNode(ctx, scope, uuid.New(), input)
	require.Equal(t, apperr.Missing, apperr.KindOf(err))
}

func TestIntegrationCrossScopeCopyUsesSeparateGrantsAndOneQuota(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, MaxCopyNodes: 100, InlineLimit: 64, MaxFileBytes: 64, MaxOutstanding: 10, MaxCleanupBacklog: 10}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "workspace"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, Service: "gateway", Gateway: true, ActorID: actor})
	fs, sourceScope, destinationScope := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 6})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{sourceScope, destinationScope}, true, true)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", sourceScope, actor, authz.ScopeWrite)
	source, err := s.CreateNode(ctx, sourceScope, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "source", File: &InlineFile{Content: []byte("abc"), MediaType: "text/plain"}})
	require.NoError(t, err)
	in := CreateCopy{SourceID: source.ID, DestinationScopeID: destinationScope, ParentID: *scopes[1].RootID, Name: "copy", Revision: &source.Revision}
	_, err = s.prepareCopy(ctx, sourceScope, uuid.New(), in)
	require.Equal(t, apperr.Forbidden, apperr.KindOf(err))
	testfixture.Grant(t, graph, "scope", destinationScope, actor, authz.ScopeWrite)
	_, err = s.GetNode(ctx, destinationScope, Locator{NodeID: &source.ID})
	require.Equal(t, apperr.Missing, apperr.KindOf(err))
	_, err = s.CreateNode(ctx, destinationScope, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "foreign"})
	require.Error(t, err)
	admission, err := s.prepareCopy(ctx, sourceScope, uuid.New(), in)
	require.NoError(t, err)
	require.NoError(t, s.copyTreeData(ctx, admission))
	copied, err := s.GetNode(ctx, destinationScope, Locator{NodeID: &admission.Root.Destination})
	require.NoError(t, err)
	require.Equal(t, destinationScope, copied.ScopeID)
	var used int64
	require.NoError(t, db.QueryRow(ctx, "SELECT used_bytes FROM filesystems WHERE id=$1", fs).Scan(&used))
	require.EqualValues(t, 6, used)
	_, err = s.CreateNode(ctx, sourceScope, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "over-quota", File: &InlineFile{Content: []byte("x"), MediaType: "text/plain"}})
	require.Equal(t, "QUOTA_EXCEEDED", reason(err))
}
