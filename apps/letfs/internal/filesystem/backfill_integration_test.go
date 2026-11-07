//go:build integration

package filesystem

import (
	"cmp"
	"slices"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
)

func TestIntegrationBackfillLiveOriginalsAndKeyset(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	s := Store{DB: db, MaxNodes: 1000}
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	fs, otherFS := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	for _, id := range []uuid.UUID{fs, otherFS} {
		_, err := s.CreateFilesystem(ctx, uuid.New(), CreateFilesystem{ID: id, LimitBytes: 1000})
		require.NoError(t, err)
	}
	scopes, err := s.CreateScopes(ctx, uuid.New(), fs, []uuid.UUID{uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())}, true, true)
	require.NoError(t, err)
	other, err := createTestScope(ctx, &s, uuid.New(), otherFS, uuid.Must(uuid.NewV7()))
	require.NoError(t, err)
	insert := func(scope uuid.UUID, parent *uuid.UUID, status string) uuid.UUID {
		t.Helper()
		id := uuid.New()
		kind := "file"
		if status == "" {
			kind = "directory"
		}
		_, err := db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind) VALUES($1,$2,$3,$4,$5)`, id, scope, parent, id.String()+".txt", kind)
		require.NoError(t, err)
		if status != "" {
			_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_format,publication_status) VALUES($1,'inline','',1,'text',$2)`, id, status)
			require.NoError(t, err)
		}
		return id
	}
	active, disabled, deleting := scopes[0], scopes[1], scopes[2]
	pending := insert(active.ID, active.RootID, "pending")
	unprocessed := insert(active.ID, active.RootID, "not_required")
	_, err = db.Exec(ctx, `UPDATE files SET desired_generation=0,processing_format=NULL WHERE node_id=$1`, unprocessed)
	require.NoError(t, err)
	ready := insert(active.ID, active.RootID, "ready")
	insert(active.ID, &pending, "pending") // Generated descendants are not originals.
	insert(active.ID, &pending, "not_required")
	insert(active.ID, &ready, "ready")
	detached := insert(active.ID, nil, "")
	insert(active.ID, &detached, "pending")
	parent, at127 := *active.RootID, *active.RootID
	for depth := 1; depth <= 128; depth++ {
		parent = insert(active.ID, &parent, "")
		if depth == 127 {
			at127 = parent
		}
	}
	deep := insert(active.ID, &at127, "pending")
	insert(active.ID, &parent, "pending") // Beyond traversal depth.
	disabledPending := insert(disabled.ID, disabled.RootID, "pending")
	insert(disabled.ID, disabled.RootID, "enriched")
	insert(disabled.ID, disabled.RootID, "ready")
	insert(deleting.ID, deleting.RootID, "pending")
	insert(other.ID, other.RootID, "ready")
	_, err = db.Exec(ctx, `UPDATE scopes SET allow_indexing=false WHERE id=$1;`, disabled.ID)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE scopes SET state='deleting' WHERE id=$1`, deleting.ID)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE filesystems SET state='deleting' WHERE id=$1`, otherFS)
	require.NoError(t, err)
	for _, test := range []struct {
		mode string
		want []uuid.UUID
	}{{"missing", []uuid.UUID{pending, deep, disabledPending, unprocessed}}, {"rebuild-index", []uuid.UUID{ready}}} {
		slices.SortFunc(test.want, func(a, b uuid.UUID) int { return cmp.Compare(a.String(), b.String()) })
		rows, err := s.BackfillCandidates(ctx, test.mode, uuid.Nil, 1000)
		require.NoError(t, err)
		ids := make([]uuid.UUID, len(rows))
		for i, row := range rows {
			ids[i] = row.Dispatch.Source.FileID
		}
		require.Equal(t, test.want, ids, test.mode)
		page, err := s.BackfillCandidates(ctx, test.mode, uuid.Nil, 1)
		require.NoError(t, err)
		require.Len(t, page, min(2, len(test.want)))
		next, err := s.BackfillCandidates(ctx, test.mode, page[0].Dispatch.Source.FileID, 1000)
		require.NoError(t, err)
		ids = ids[:0]
		for _, row := range next {
			ids = append(ids, row.Dispatch.Source.FileID)
		}
		require.Equal(t, test.want[1:], ids)
	}
	for _, mode := range []string{"invalid", ""} {
		_, err := s.BackfillCandidates(ctx, mode, uuid.Nil, 1)
		require.Equal(t, "VALIDATION", reason(err))
	}
}
