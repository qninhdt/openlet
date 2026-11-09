//go:build integration

package filesystem

import (
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationRootRestrictedLocator(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, MaxCopyNodes: 100, InlineLimit: 128, MaxFileBytes: 128, MaxOutstanding: 10, MaxCleanupBacklog: 10}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: actor, Service: "gateway", Gateway: true})
	fsID, scopeID := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fsID, LimitBytes: 4096})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(owner, uuid.New(), fsID, []uuid.UUID{scopeID}, true, true)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", scopeID, actor, authz.ScopeWrite, authz.ScopeTrash)
	box, err := s.CreateNode(ctx, scopeID, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "box"})
	require.NoError(t, err)
	file, err := s.CreateNode(ctx, scopeID, uuid.New(), CreateNode{Parent: Locator{NodeID: &box.ID, RootID: &box.ID}, Name: "notes.txt", File: &InlineFile{Content: []byte("hello\n"), MediaType: "text/plain"}})
	require.NoError(t, err)
	outside, err := s.CreateNode(ctx, scopeID, uuid.New(), CreateNode{Parent: Locator{NodeID: scopes[0].RootID}, Name: "outside"})
	require.NoError(t, err)
	for _, locator := range []Locator{
		{Path: ptr("/notes.txt"), RootID: &box.ID},
		{Path: ptr("/@" + file.ID.String()), RootID: &box.ID},
		{Path: ptr("notes.txt"), CwdID: &box.ID, RootID: &box.ID},
		{NodeID: &file.ID, RootID: &box.ID},
	} {
		got, err := s.ResolveNode(ctx, scopeID, locator)
		require.NoError(t, err)
		require.Equal(t, file.ID, got.ID)
	}
	for _, locator := range []Locator{
		{Path: ptr("/../box/notes.txt"), RootID: &box.ID},
		{Path: ptr("/@" + outside.ID.String()), RootID: &box.ID},
		{Path: ptr("../box/notes.txt"), CwdID: &outside.ID, RootID: &box.ID},
		{NodeID: &outside.ID, RootID: &box.ID},
		{NodeID: scopes[0].RootID, RootID: &box.ID},
		{NodeID: &file.ID, RootID: &file.ID},
	} {
		_, err := s.ResolveNode(ctx, scopeID, locator)
		require.Equal(t, "NOT_FOUND", reason(err), "%+v", locator)
	}
	root, err := s.ResolveNode(ctx, scopeID, Locator{Path: ptr("/"), RootID: &box.ID})
	require.NoError(t, err)
	require.Equal(t, box.ID, root.ID)
	_, err = s.UpdateNode(ctx, scopeID, UpdateNode{Locator: Locator{NodeID: &box.ID, RootID: &box.ID}, Revision: &root.Revision, Name: ptr("renamed")})
	require.Equal(t, "ROOT_IMMUTABLE", reason(err))
	_, err = s.TrashNode(ctx, scopeID, Locator{NodeID: &box.ID, RootID: &box.ID}, &root.Revision, false)
	require.Equal(t, "ROOT_IMMUTABLE", reason(err))
	_, err = s.UpdateNode(ctx, scopeID, UpdateNode{Locator: Locator{NodeID: &file.ID, RootID: &box.ID}, Revision: &file.Revision, Parent: &Locator{NodeID: &outside.ID}})
	require.Equal(t, "NOT_FOUND", reason(err), "omitted destination boundary inherits the same-scope source root")
	_, err = s.ReplaceContent(ctx, scopeID, Locator{NodeID: &outside.ID, RootID: &box.ID}, &outside.Revision, []byte("blocked"), "text/plain")
	require.Equal(t, "NOT_FOUND", reason(err))
	_, err = s.CreateNode(ctx, scopeID, uuid.New(), CreateNode{Parent: Locator{NodeID: &box.ID, RootID: &box.ID}, Name: "@" + uuid.NewString()})
	require.Equal(t, "VALIDATION", reason(err), "mount root reserves UUID aliases")
	_, err = s.CopyNode(ctx, scopeID, uuid.New(), CreateCopy{SourceID: file.ID, ParentID: outside.ID, Name: "escape", Revision: &file.Revision, SourceRootID: &box.ID})
	require.Equal(t, "NOT_FOUND", reason(err))
	_, err = s.CopyNode(ctx, scopeID, uuid.New(), CreateCopy{SourceID: outside.ID, ParentID: box.ID, Name: "outside-copy", Revision: &outside.Revision, SourceRootID: &box.ID, DestinationRootID: &box.ID})
	require.Equal(t, "NOT_FOUND", reason(err))
	copied, err := s.CopyNode(ctx, scopeID, uuid.New(), CreateCopy{SourceID: file.ID, ParentID: box.ID, Name: "copy.txt", Revision: &file.Revision, SourceRootID: &box.ID, DestinationRootID: &box.ID})
	require.NoError(t, err)
	entry, err := s.TrashNode(ctx, scopeID, Locator{NodeID: &copied.ID, RootID: &box.ID}, &copied.Revision, false)
	require.NoError(t, err)
	_, err = s.RestoreTrash(ctx, scopeID, entry.ID, RestoreTrash{RootID: &outside.ID, Parent: &Locator{NodeID: &outside.ID, RootID: &outside.ID}})
	require.Equal(t, "NOT_FOUND", reason(err), "cannot adopt another mount's trash")
	_, err = s.RestoreTrash(ctx, scopeID, entry.ID, RestoreTrash{RootID: &box.ID, Parent: &Locator{NodeID: &outside.ID}})
	require.Equal(t, "NOT_FOUND", reason(err), "restore inherits its source boundary")
	_, err = s.RestoreTrash(ctx, scopeID, entry.ID, RestoreTrash{RootID: &box.ID})
	require.NoError(t, err)
	artifactDir, artifact := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind) VALUES($1,$2,$3,'parts','directory'),($4,$2,$1,'README.md','file')`, artifactDir, scopeID, file.ID, artifact)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes) VALUES($1,'inline','artifact')`, artifact)
	require.NoError(t, err)
	got, err := s.ResolveNode(ctx, scopeID, Locator{Path: ptr("/notes.txt/parts/README.md"), RootID: &box.ID})
	require.NoError(t, err)
	require.Equal(t, artifact, got.ID)
	require.True(t, got.readonly)
	page, err := s.ListNodes(ctx, scopeID, Locator{NodeID: &artifactDir, RootID: &box.ID}, nil, nil)
	require.NoError(t, err)
	require.Len(t, page.Items, 1)
	require.True(t, page.Items[0].readonly)
	_, err = s.ResolveNode(ctx, scopeID, Locator{NodeID: &artifact, RootID: &artifactDir})
	require.Equal(t, "NOT_FOUND", reason(err), "generated directory cannot become a writable mount root")
	root, err = s.GetNode(ctx, scopeID, Locator{NodeID: &box.ID})
	require.NoError(t, err)
	_, err = s.TrashNode(ctx, scopeID, Locator{NodeID: &box.ID}, &root.Revision, false)
	require.NoError(t, err)
	_, err = s.ResolveNode(ctx, scopeID, Locator{NodeID: &file.ID, RootID: &box.ID})
	require.Equal(t, "NOT_FOUND", reason(err), "detached mount roots are not live")
}
