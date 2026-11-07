//go:build integration

package filesystem

import (
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/search"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
)

func TestIntegrationSemanticHydrationAncestryPathsAndDepth(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	s := Store{DB: db, MaxNodes: 1000, IndexSpace: VectorSpace{Model: "test", Dimension: 2}}
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	fs, scope, foreign := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateFilesystem(ctx, uuid.New(), CreateFilesystem{ID: fs, LimitBytes: 1000})
	require.NoError(t, err)
	scopes, err := s.CreateScopes(ctx, uuid.New(), fs, []uuid.UUID{scope, foreign}, true, true)
	require.NoError(t, err)
	root := *scopes[0].RootID
	insert := func(parent *uuid.UUID, name, kind string, scopeID uuid.UUID) uuid.UUID {
		t.Helper()
		id := uuid.New()
		_, err := db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind) VALUES($1,$2,$3,$4,$5)`, id, scopeID, parent, name, kind)
		require.NoError(t, err)
		if kind == "file" {
			_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_format,publication_status) VALUES($1,'inline','',1,'text','ready')`, id)
			require.NoError(t, err)
		}
		return id
	}
	outer := insert(&root, "outer", "directory", scope)
	selected := insert(&outer, "Việt", "directory", scope)
	source := insert(&selected, "report.pdf", "file", scope)
	artifactDir := insert(&source, "chapters", "directory", scope)
	artifact := insert(&artifactDir, "one.md", "file", scope)
	outside := insert(&outer, "outside.txt", "file", scope)
	detached := insert(nil, "detached", "directory", scope)
	hidden := insert(&detached, "hidden.txt", "file", scope)
	foreignFile := insert(scopes[1].RootID, "foreign.txt", "file", foreign)
	point := func(source, file uuid.UUID, generation int64) search.Point {
		return search.Point{Payload: search.Payload{ScopeID: scope, SourceID: source, FileID: file, Generation: generation, EmbeddingModel: "test", VectorDimension: 2, Text: "evidence"}}
	}
	points := []search.Point{point(source, artifact, 1), point(source, artifact, 1), point(outside, outside, 1),
		point(source, outside, 1), point(source, artifact, 2), point(artifact, artifact, 1), point(hidden, hidden, 1), point(foreignFile, foreignFile, 1)}
	query := SemanticSearchInput{Query: "evidence", Filters: SearchFilters{Parent: &Locator{NodeID: &selected}}}
	items, err := s.hydrateSearch(ctx, scope, query, points)
	require.NoError(t, err)
	require.Len(t, items, 2)
	for _, index := range []int{0, 1} {
		require.Equal(t, source, items[index].Node.ID)
		require.Equal(t, "/outer/Việt/report.pdf", items[index].Path)
		require.Equal(t, []Breadcrumb{{source, "report.pdf"}, {artifactDir, "chapters"}, {artifact, "one.md"}}, items[index].Matched.Breadcrumb)
	}
	query.Filters.Parent = nil
	items, err = s.hydrateSearch(ctx, scope, query, points)
	require.NoError(t, err)
	require.Len(t, items, 3)
	require.Equal(t, "/outer/outside.txt", items[2].Path)
	query.Filters.MediaType = ptr("application/pdf")
	items, err = s.hydrateSearch(ctx, scope, query, points)
	require.NoError(t, err)
	require.Empty(t, items)
	_, err = db.Exec(ctx, `UPDATE nodes SET parent_id=NULL WHERE id=$1`, outer)
	require.NoError(t, err)
	query.Filters = SearchFilters{}
	items, err = s.hydrateSearch(ctx, scope, query, points)
	require.NoError(t, err)
	require.Empty(t, items, "current detached ancestry excludes every descendant")
	query.Filters.Parent = &Locator{NodeID: &selected}
	_, err = s.hydrateSearch(ctx, scope, query, nil)
	require.Equal(t, "NOT_FOUND", reason(err), "empty provider evidence still validates its search parent")

	parent, at127 := root, root
	for depth := 1; depth <= maxDepth; depth++ {
		parent = insert(&parent, "level", "directory", scope)
		if depth == maxDepth-1 {
			at127 = parent
		}
	}
	deep := insert(&at127, "deep.txt", "file", scope)
	tooDeep := insert(&parent, "too-deep.txt", "file", scope)
	items, err = s.hydrateSearch(ctx, scope, SemanticSearchInput{}, []search.Point{point(deep, deep, 1), point(tooDeep, tooDeep, 1)})
	require.NoError(t, err)
	require.Len(t, items, 1, "only originals within the search traversal depth are visible")
	require.Equal(t, deep, items[0].Node.ID)
}
