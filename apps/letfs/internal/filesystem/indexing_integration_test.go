//go:build integration

package filesystem

import (
	"github.com/qninhdt/openlet/packages/go/apperr"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
)

func TestIntegrationIndexPublicationAndGenerationFences(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	s := Store{DB: db, MaxNodes: 100, ProcessingMaxOutputs: 10, IndexSpace: VectorSpace{Model: "embedding-v1", Collection: "files", Dimension: 8}}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	bucket, fs, file := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateBucket(owner, uuid.New(), CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'notes.txt','file',1)`, file, fs, created.RootID)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_format,publication_status)
 VALUES($1,'inline','x',1,'text','parsed')`, file)
	require.NoError(t, err)
	source := Generation{FileID: file, Generation: 1}
	_, err = s.PrepareIndex(t.Context(), source)
	require.Equal(t, "PUBLICATION_NOT_COMPLETE", reason(err))
	_, err = db.Exec(t.Context(), `UPDATE files SET publication_status='enriched' WHERE node_id=$1`, file)
	require.NoError(t, err)
	prepared, err := s.PrepareIndex(t.Context(), source)
	require.NoError(t, err)
	require.False(t, prepared.Complete)
	require.Equal(t, fs, prepared.FilesystemID)
	require.Equal(t, s.IndexSpace, prepared.VectorSpace)
	require.Len(t, prepared.Nodes, 1)
	require.Equal(t, []byte("x"), prepared.Nodes[0].Content.InlineContent)
	require.NoError(t, s.FailIndex(t.Context(), source, "DEPENDENCY_UNAVAILABLE"))
	var state string
	require.NoError(t, db.QueryRow(t.Context(), `SELECT publication_status FROM files WHERE node_id=$1`, file).Scan(&state))
	require.Equal(t, "index_failed", state)
	_, err = s.PrepareIndex(t.Context(), source)
	require.NoError(t, err)
	require.NoError(t, s.CompleteIndex(t.Context(), source))
	require.NoError(t, s.CompleteIndex(t.Context(), source))
	require.NoError(t, s.FailIndex(t.Context(), source, "PROCESSING_FAILED"))
	ready, err := s.PrepareIndex(t.Context(), source)
	require.NoError(t, err)
	require.True(t, ready.Complete, "late failure cannot undo ready index")
	require.Empty(t, ready.Nodes)
	_, err = db.Exec(t.Context(), `UPDATE files SET desired_generation=2,publication_status='parsed' WHERE node_id=$1`, file)
	require.NoError(t, err)
	require.Equal(t, "SOURCE_REPLACED", reason(s.CompleteIndex(t.Context(), source)))
	_, err = s.PrepareIndex(t.Context(), source)
	require.Equal(t, "SOURCE_REPLACED", reason(err))
	require.Equal(t, "SOURCE_REPLACED", reason(s.FailIndex(t.Context(), source, "PROCESSING_FAILED")))
	require.Equal(t, apperr.Invalid, apperr.KindOf(s.CompleteIndex(t.Context(), Generation{})))
}
