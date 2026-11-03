//go:build integration

package filesystem

import (
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"openlet/apps/letfs/internal/testfixture"
	"openlet/packages/go/identity"
)

func TestIntegrationIndexPublicationSpaceAndGenerationFences(t *testing.T) {
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
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_actor_id,processing_format,processing_source_identity,publication_status,index_status)
 VALUES($1,'inline','x',1,$2,'text','inline:2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881','parsed','pending')`, file, uuid.New())
	require.NoError(t, err)
	source := Generation{FileID: file, Generation: 1}
	_, err = s.PrepareIndex(t.Context(), source)
	require.Equal(t, "PUBLICATION_NOT_COMPLETE", reason(err))
	_, err = db.Exec(t.Context(), `UPDATE files SET publication_status='ready',published_generation=1 WHERE node_id=$1`, file)
	require.NoError(t, err)
	prepared, err := s.PrepareIndex(t.Context(), source)
	require.NoError(t, err)
	require.False(t, prepared.Complete)
	require.Equal(t, fs, prepared.FilesystemID)
	require.Equal(t, s.IndexSpace, prepared.VectorSpace)
	require.Len(t, prepared.Nodes, 1)
	require.Equal(t, []byte("x"), prepared.Nodes[0].Content.InlineContent)
	require.NoError(t, s.FailIndex(t.Context(), source, s.IndexSpace, "DEPENDENCY_UNAVAILABLE"))
	var state string
	require.NoError(t, db.QueryRow(t.Context(), `SELECT index_status FROM files WHERE node_id=$1`, file).Scan(&state))
	require.Equal(t, "failed", state)
	_, err = s.PrepareIndex(t.Context(), source)
	require.NoError(t, err)
	require.NoError(t, s.CompleteIndex(t.Context(), source, s.IndexSpace))
	require.NoError(t, s.CompleteIndex(t.Context(), source, s.IndexSpace))
	require.NoError(t, s.FailIndex(t.Context(), source, s.IndexSpace, "PROCESSING_FAILED"))
	ready, err := s.PrepareIndex(t.Context(), source)
	require.NoError(t, err)
	require.True(t, ready.Complete, "late failure cannot undo ready index")
	require.Empty(t, ready.Nodes)
	old := s.IndexSpace
	s.IndexSpace = VectorSpace{Model: "embedding-v2", Collection: "files-v2", Dimension: 16}
	require.Equal(t, "VECTOR_SPACE_CHANGED", reason(s.CompleteIndex(t.Context(), source, old)), "completion rejects obsolete configured space before prepare")
	prepared, err = s.PrepareIndex(t.Context(), source)
	require.NoError(t, err)
	require.False(t, prepared.Complete)
	require.Equal(t, s.IndexSpace, prepared.VectorSpace)
	var deleted VectorSpace
	require.NoError(t, db.QueryRow(t.Context(), `SELECT embedding_model,vector_collection,vector_dimension FROM index_deletions WHERE file_id=$1 AND generation=1`, file).Scan(&deleted.Model, &deleted.Collection, &deleted.Dimension))
	require.Equal(t, old, deleted, "tombstone retains exact obsolete vector space")
	require.Equal(t, "VECTOR_SPACE_CHANGED", reason(s.CompleteIndex(t.Context(), source, old)))
	require.Equal(t, "VECTOR_SPACE_CHANGED", reason(s.FailIndex(t.Context(), source, old, "PROCESSING_FAILED")))
	require.NoError(t, s.CompleteIndex(t.Context(), source, s.IndexSpace))
	_, err = db.Exec(t.Context(), `UPDATE files SET desired_generation=2,publication_status='parsed',published_generation=NULL,index_status='pending',indexed_generation=NULL WHERE node_id=$1`, file)
	require.NoError(t, err)
	require.Equal(t, "SOURCE_REPLACED", reason(s.CompleteIndex(t.Context(), source, s.IndexSpace)))
	_, err = s.PrepareIndex(t.Context(), source)
	require.Equal(t, "SOURCE_REPLACED", reason(err))
	require.Equal(t, "SOURCE_REPLACED", reason(s.FailIndex(t.Context(), source, s.IndexSpace, "PROCESSING_FAILED")))
	source.Generation = 2
	_, err = db.Exec(t.Context(), `UPDATE files SET inline_bytes='y' WHERE node_id=$1`, file)
	require.NoError(t, err)
	_, err = s.PrepareIndex(t.Context(), source)
	require.Equal(t, "SOURCE_REPLACED", reason(err), "generation alone does not bypass immutable source identity")
	require.Equal(t, codes.InvalidArgument, status.Code(s.CompleteIndex(t.Context(), Generation{}, s.IndexSpace)))
}
