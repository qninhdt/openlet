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

func TestIntegrationEnrichmentDirectChildrenPublishAtomicallyAndPreserveSource(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	s := Store{DB: db, MaxNodes: 100, InlineLimit: 100, MaxFileBytes: 100, ProcessingMaxOutputs: 20, ProcessingMaxOutputBytes: 200}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	bucket, fs, file := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateBucket(owner, uuid.New(), CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'report.pdf','file',1)`, file, fs, created.RootID)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_format,publication_status)
 VALUES($1,'inline','x',1,'pdf','pending')`, file)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `UPDATE filesystems SET node_count=2 WHERE id=$1`, fs)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `UPDATE quota_buckets SET used_bytes=1 WHERE id=$1`, bucket)
	require.NoError(t, err)
	a := Generation{FileID: file, Generation: 1}
	_, err = s.PrepareParse(t.Context(), a)
	require.NoError(t, err)
	_, err = s.PrepareEnrichment(t.Context(), a)
	require.Equal(t, "PARSE_NOT_COMPLETE", reason(err))
	write := func(stage, name string, content []byte) uuid.UUID {
		t.Helper()
		size := int64(len(content))
		input := ProcessingOutput{Path: name, Storage: "inline", SizeBytes: &size}
		var output Upload
		var err error
		if stage == "parse" {
			output, err = s.PrepareParseOutput(t.Context(), a, input)
		} else {
			output, err = s.PrepareEnrichmentOutput(t.Context(), a, input)
		}
		require.NoError(t, err)
		scope := OutputScope{Source: a, Stage: stage, UploadID: output.ID}
		_, err = s.WriteOutputBytes(t.Context(), scope, content)
		require.NoError(t, err)
		_, err = s.CompleteOutputUpload(t.Context(), scope, nil)
		require.NoError(t, err)
		return output.ID
	}
	uploads := []uuid.UUID{write("parse", "README.md", []byte("root")), write("parse", "part/README.md", []byte("section")), write("parse", "part/leaf.md", []byte("leaf"))}
	require.NoError(t, s.CompleteParse(t.Context(), a, ParseManifest{Uploads: uploads}))
	prepared, err := s.PrepareEnrichment(t.Context(), a)
	require.NoError(t, err)
	require.Len(t, prepared.Nodes, 5)
	require.Equal(t, file, prepared.Nodes[0].ID)
	require.Equal(t, "file", prepared.Nodes[0].Kind)
	require.Nil(t, prepared.Nodes[0].Content, "parsed original bytes are not evidence")
	var readme, leaf uuid.UUID
	updates := make([]EnrichmentUpdate, 0, len(prepared.Nodes))
	metadata := &SemanticMetadata{Title: "Summary", Description: "Own text.", SemanticType: "document:report", Context: "Search evidence."}
	for _, node := range prepared.Nodes {
		update := EnrichmentUpdate{ID: node.ID, Path: node.Path}
		switch node.Path {
		case "":
			update.Metadata = &SemanticMetadata{Title: "Ignored source", Description: "Source", SemanticType: "document:other", Context: "Source"}
		case "part":
			update.Path = "section"
		default:
			update.Metadata = metadata
			if node.Path == "README.md" {
				readme = node.ID
				update.Path = "README.md"
			} else if node.Name == "README.md" {
				update.Path = "section/README.md"
			} else {
				leaf = node.ID
				update.Path = "section/renamed.md"
			}
			id := write("enrichment", update.Path, []byte("rewritten "+update.Path))
			update.UploadID = &id
		}
		updates = append(updates, update)
	}
	manifest := EnrichmentManifest{Nodes: updates}
	var before int64
	require.NoError(t, db.QueryRow(t.Context(), `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&before))
	_, err = db.Exec(t.Context(), `UPDATE quota_buckets SET limit_bytes=used_bytes WHERE id=$1`, bucket)
	require.NoError(t, err)
	require.Equal(t, "QUOTA_EXCEEDED", reason(s.CompleteEnrichment(t.Context(), a, manifest)))
	var name, publication string
	var content []byte
	require.NoError(t, db.QueryRow(t.Context(), `SELECT name FROM nodes WHERE id=$1`, leaf).Scan(&name))
	require.Equal(t, "leaf.md", name)
	require.NoError(t, db.QueryRow(t.Context(), `SELECT publication_status FROM files WHERE node_id=$1`, file).Scan(&publication))
	require.Equal(t, "parsed", publication)
	var used int64
	require.NoError(t, db.QueryRow(t.Context(), `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.Equal(t, before, used)
	_, err = db.Exec(t.Context(), `UPDATE quota_buckets SET limit_bytes=1000 WHERE id=$1`, bucket)
	require.NoError(t, err)
	require.NoError(t, s.CompleteEnrichment(t.Context(), a, manifest))
	require.NoError(t, s.CompleteEnrichment(t.Context(), a, manifest))
	require.NoError(t, db.QueryRow(t.Context(), `SELECT name FROM nodes WHERE id=$1`, file).Scan(&name))
	require.Equal(t, "report.pdf", name)
	var title string
	require.NoError(t, db.QueryRow(t.Context(), `SELECT inline_bytes,title,publication_status FROM files WHERE node_id=$1`, file).Scan(&content, &title, &publication))
	require.Equal(t, []byte("x"), content)
	require.Equal(t, "Summary", title)
	require.Equal(t, "enriched", publication)
	require.NoError(t, db.QueryRow(t.Context(), `SELECT name FROM nodes WHERE id=$1`, leaf).Scan(&name))
	require.Equal(t, "renamed.md", name)
	require.NoError(t, db.QueryRow(t.Context(), `SELECT inline_bytes FROM files WHERE node_id=$1`, readme).Scan(&content))
	require.Equal(t, []byte("rewritten README.md"), content)
	complete, err := s.PrepareEnrichment(t.Context(), a)
	require.NoError(t, err)
	require.True(t, complete.Complete)
	require.NoError(t, s.FailEnrichment(t.Context(), a, "PROCESSING_FAILED"), "late failure cannot undo committed publication")
	require.Equal(t, apperr.Invalid, apperr.KindOf(s.FailEnrichment(t.Context(), a, "secret provider text")))
}

func TestIntegrationEnrichmentDirectSourceNeedsNoOutputAndFencesRetries(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	s := Store{DB: db, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 64, ProcessingMaxOutputs: 10, ProcessingMaxOutputBytes: 100}
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
	a := Generation{FileID: file, Generation: 1}
	prepared, err := s.PrepareEnrichment(t.Context(), a)
	require.NoError(t, err)
	require.Len(t, prepared.Nodes, 1)
	require.Equal(t, []byte("x"), prepared.Nodes[0].Content.InlineContent)
	manifest := EnrichmentManifest{Nodes: []EnrichmentUpdate{{ID: file, Metadata: &SemanticMetadata{Title: "Notes", Description: "Direct content.", SemanticType: "text:notes", Context: "Search evidence."}}}}
	require.NoError(t, s.CompleteEnrichment(t.Context(), a, manifest))
	var count int64
	require.NoError(t, db.QueryRow(t.Context(), `SELECT count(*) FROM nodes WHERE parent_id=$1`, file).Scan(&count))
	require.Zero(t, count)
}
