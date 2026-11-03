//go:build integration

package temporal

import (
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"openlet/apps/letfs/internal/filesystem"
	"openlet/apps/letfs/internal/testfixture"
	"openlet/packages/go/identity"
)

func TestIntegrationBackfillDryRunMissingAndIndexOnly(t *testing.T) {
	tc, _ := testfixture.Temporal(t)
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	store := &filesystem.Store{DB: db, MaxNodes: 100, IndexSpace: filesystem.VectorSpace{Model: "embedding-v2", Collection: "files-v2", Dimension: 4}}
	jobs := &Jobs{Client: tc}
	activities := &Activities{Store: store, Jobs: jobs}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	bucket, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := store.CreateBucket(owner, uuid.New(), filesystem.CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	files := []uuid.UUID{}
	for _, name := range []string{"a.txt", "b.pdf", "c.bin", "detached.txt"} {
		id := uuid.Must(uuid.NewV7())
		_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,$4,'file',1)`, id, fs, created.RootID, name)
		require.NoError(t, err)
		_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes) VALUES($1,'inline','x')`, id)
		require.NoError(t, err)
		files = append(files, id)
	}
	_, err = db.Exec(t.Context(), `UPDATE nodes SET parent_id=NULL WHERE id=$1`, files[3])
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `UPDATE files SET desired_generation=2,processing_actor_id=$2,processing_format='pdf',processing_source_identity='inline:2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881',publication_status='ready',published_generation=2,index_status='ready',indexed_generation=2,embedding_model='embedding-v1',vector_collection='files-v1',vector_dimension=2,parse_manifest_hash='parse-manifest',publication_manifest_hash='semantic-manifest' WHERE node_id=$1`, files[1], uuid.New())
	require.NoError(t, err)
	child := uuid.New()
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind) VALUES($1,$2,$3,'README.md','file')`, child, fs, files[1])
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes) VALUES($1,'inline','generated')`, child)
	require.NoError(t, err)
	input := BackfillOptions{Mode: "missing", Limit: 1}
	result, err := activities.Backfill(t.Context(), input)
	require.NoError(t, err)
	require.Equal(t, 1, result.Scanned)
	require.Equal(t, 1, result.Eligible)
	require.Zero(t, result.Applied)
	require.Equal(t, &files[0], result.NextCursor)
	var generation int64
	require.NoError(t, db.QueryRow(t.Context(), `SELECT desired_generation FROM files WHERE node_id=$1`, files[0]).Scan(&generation))
	require.Zero(t, generation, "dry-run must not admit processing")
	input.After = *result.NextCursor
	result, err = activities.Backfill(t.Context(), input)
	require.NoError(t, err)
	require.Equal(t, 1, result.Scanned)
	require.Zero(t, result.Eligible, "unsupported file is scanned but not eligible")
	require.Nil(t, result.NextCursor, "ready, generated and detached files are excluded from missing mode")
	input.After, input.Limit, input.Apply = uuid.Nil, 100, true
	result, err = activities.Backfill(t.Context(), input)
	require.NoError(t, err)
	require.Equal(t, 1, result.Applied)
	var source, publication string
	require.NoError(t, db.QueryRow(t.Context(), `SELECT desired_generation,processing_source_identity,publication_status FROM files WHERE node_id=$1`, files[0]).Scan(&generation, &source, &publication))
	require.EqualValues(t, 1, generation)
	require.Equal(t, "inline:2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881", source)
	require.Equal(t, "parsed", publication)
	pendingID := (filesystem.Generation{FileID: files[0], Generation: 1}).WorkflowID()
	running, err := jobs.WorkflowStatus(t.Context(), pendingID, nil)
	require.NoError(t, err)
	require.NotNil(t, running)
	require.True(t, *running)
	result, err = activities.Backfill(t.Context(), input)
	require.NoError(t, err)
	require.Zero(t, result.Applied, "an active processing workflow is skipped")
	input.Mode = "rebuild-index"
	result, err = activities.Backfill(t.Context(), input)
	require.NoError(t, err)
	require.Equal(t, 1, result.Scanned)
	require.Equal(t, 1, result.Applied)
	var manifest, parseManifest, index string
	var parent uuid.UUID
	var content []byte
	require.NoError(t, db.QueryRow(t.Context(), `SELECT desired_generation,publication_status,index_status,publication_manifest_hash,parse_manifest_hash,inline_bytes FROM files WHERE node_id=$1`, files[1]).Scan(&generation, &publication, &index, &manifest, &parseManifest, &content))
	require.EqualValues(t, 2, generation)
	require.Equal(t, "ready", publication)
	require.Equal(t, "pending", index)
	require.Equal(t, "semantic-manifest", manifest)
	require.Equal(t, "parse-manifest", parseManifest)
	require.Equal(t, []byte("x"), content)
	require.NoError(t, db.QueryRow(t.Context(), `SELECT parent_id FROM nodes WHERE id=$1`, child).Scan(&parent))
	require.Equal(t, files[1], parent, "index-only rebuild preserves parsed outputs")
	var count int
	require.NoError(t, db.QueryRow(t.Context(), `SELECT count(*) FROM index_deletions WHERE file_id=$1 AND generation=2 AND embedding_model='embedding-v1' AND vector_collection='files-v1' AND vector_dimension=2`, files[1]).Scan(&count))
	require.Equal(t, 1, count)
	indexID, err := (filesystem.Generation{FileID: files[1], Generation: 2}).IndexWorkflowID(store.IndexSpace)
	require.NoError(t, err)
	running, err = jobs.WorkflowStatus(t.Context(), indexID, nil)
	require.NoError(t, err)
	require.NotNil(t, running)
	require.True(t, *running)
	result, err = activities.Backfill(t.Context(), input)
	require.NoError(t, err)
	require.Zero(t, result.Applied, "an active index-only workflow is skipped")
	observed, err := store.BackfillCandidates(t.Context(), "rebuild-index", uuid.Nil, 100)
	require.NoError(t, err)
	require.Len(t, observed, 1)
	_, err = db.Exec(t.Context(), `UPDATE files SET desired_generation=3,publication_status='pending',published_generation=NULL,indexed_generation=NULL,processing_updated_at=now() WHERE node_id=$1`, files[1])
	require.NoError(t, err)
	applied, err := store.AdmitBackfill(t.Context(), observed[0], uuid.New())
	require.NoError(t, err)
	require.False(t, applied, "a changed source after workflow observation cannot be admitted")
}
