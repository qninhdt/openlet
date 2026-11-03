//go:build integration

package filesystem

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"openlet/apps/letfs/internal/testfixture"
	"openlet/packages/go/authz"
	"openlet/packages/go/identity"
	sharedfixture "openlet/packages/go/testfixture"
)

func TestIntegrationParsePreparationFencesAttemptsGenerationAndContent(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 64}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	bucket, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateBucket(owner, uuid.New(), CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	mounts := []Mount{{Path: "/", FilesystemID: fs}}
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeCreate, authz.NodeRead, authz.ContentWrite, authz.NodeTrash)
	file, err := s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: "report.docx",
		File: &InlineFile{Content: []byte{0, 255, 1}, MediaType: "application/octet-stream"}})
	require.NoError(t, err)
	pipeline := t.Context()
	first := ProcessingAttempt{Source: Generation{FileID: file.ID, Generation: 1}, Number: 1, ID: uuid.New()}
	prepared, err := s.PrepareParse(pipeline, first)
	require.NoError(t, err)
	require.Equal(t, "docx", prepared.Format)
	require.Equal(t, file.ID, prepared.SourceID)
	require.EqualValues(t, 3, prepared.SizeBytes)
	require.Equal(t, []byte{0, 255, 1}, prepared.InlineContent)
	require.Empty(t, prepared.SignedURL)
	require.False(t, prepared.Complete)
	replayed, err := s.PrepareParse(pipeline, first)
	require.NoError(t, err)
	require.Equal(t, prepared, replayed)
	for _, number := range []int32{0, 4} {
		invalid := first
		invalid.Number = number
		_, err = s.PrepareParse(pipeline, invalid)
		require.Equal(t, codes.InvalidArgument, status.Code(err))
	}
	output := uuid.New()
	_, err = db.Exec(pipeline, `INSERT INTO uploads(id,filesystem_id,bucket_id,actor_id,input,candidate_key,transport,expected_size,content_md5,
 processing_file_id,processing_generation,processing_attempt,processing_attempt_id,relative_path,processing_stage,write_expires_at)
 VALUES($1,$2,$3,$4,'{}','processing/old-output','single',3,'Mhw89IbtUJFk7eweGYH+yA==',$5,1,1,$6,'text.txt','parse',now()+interval '1 minute')`, output, fs, bucket, actor, file.ID, first.ID)
	require.NoError(t, err)
	second := first
	second.Number, second.ID = 2, uuid.New()
	_, err = s.PrepareParse(pipeline, second)
	require.NoError(t, err)
	var state string
	require.NoError(t, db.QueryRow(pipeline, `SELECT state FROM uploads WHERE id=$1`, output).Scan(&state))
	require.Equal(t, "aborted", state)
	var queued bool
	require.NoError(t, db.QueryRow(pipeline, `SELECT ambiguous_write FROM object_deletions WHERE object_key='processing/old-output'`).Scan(&queued))
	require.True(t, queued)
	_, err = s.PrepareParse(pipeline, first)
	require.Equal(t, "STALE_PROCESSING_ATTEMPT", reason(err))
	spoofed := second
	spoofed.ID = uuid.New()
	_, err = s.PrepareParse(pipeline, spoofed)
	require.Equal(t, "STALE_PROCESSING_ATTEMPT", reason(err))
	require.Equal(t, "STALE_PROCESSING_ATTEMPT", reason(s.AbortParse(pipeline, first, "PROCESSING_FAILED")))
	file, err = s.ReplaceContent(ctx, fs, mounts, Locator{NodeID: &file.ID}, &file.Revision, []byte("replacement"), "application/octet-stream")
	require.NoError(t, err)
	_, err = s.PrepareParse(pipeline, second)
	require.Equal(t, "SOURCE_REPLACED", reason(err))
	current := ProcessingAttempt{Source: Generation{FileID: file.ID, Generation: 2}, Number: 1, ID: uuid.New()}
	_, err = s.PrepareParse(pipeline, current)
	require.NoError(t, err)
	_, err = db.Exec(pipeline, `UPDATE files SET inline_bytes='changed' WHERE node_id=$1`, file.ID)
	require.NoError(t, err)
	_, err = s.PrepareParse(pipeline, current)
	require.Equal(t, "SOURCE_REPLACED", reason(err), "generation alone is not a content identity")
	_, err = db.Exec(pipeline, `UPDATE files SET inline_bytes='replacement' WHERE node_id=$1`, file.ID)
	require.NoError(t, err)
	require.Equal(t, codes.InvalidArgument, status.Code(s.AbortParse(pipeline, current, "private provider text")))
	_, err = s.FreezeBucket(owner, uuid.New(), bucket)
	require.NoError(t, err)
	require.NoError(t, s.AbortParse(pipeline, current, "PROCESSING_CANCELLED"), "cleanup is still allowed after freeze")
	var errorCode string
	require.NoError(t, db.QueryRow(pipeline, `SELECT publication_status,processing_error FROM files WHERE node_id=$1`, file.ID).Scan(&state, &errorCode))
	require.Equal(t, "failed", state)
	require.Equal(t, "PROCESSING_CANCELLED", errorCode)
	_, err = s.PrepareParse(pipeline, current)
	require.Equal(t, "BUCKET_FROZEN", reason(err))
	canceled, cancel := context.WithCancel(pipeline)
	cancel()
	_, err = s.PrepareParse(canceled, current)
	require.ErrorIs(t, err, context.Canceled)
}

func TestIntegrationParseOutputPublicationAtomicReplayAndScope(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	s := Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 64, ProcessingMaxOutputs: 10, ProcessingMaxOutputBytes: 100}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	bucket, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := s.CreateBucket(owner, uuid.New(), CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	mounts := []Mount{{Path: "/", FilesystemID: fs}}
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.NodeCreate, authz.NodeRead, authz.NodeList, authz.ContentWrite, authz.UploadRead)
	source, err := s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: "document.pdf", File: &InlineFile{Content: []byte("pdf"), MediaType: "application/pdf"}})
	require.NoError(t, err)
	a := ProcessingAttempt{Source: Generation{FileID: source.ID, Generation: 1}, Number: 1, ID: uuid.New()}
	_, err = s.PrepareParse(t.Context(), a)
	require.NoError(t, err)
	size := int64(3)
	output := ProcessingOutput{Path: "pages/text.md", Storage: "inline", SizeBytes: &size}
	upload, err := s.PrepareParseOutput(t.Context(), a, output)
	require.NoError(t, err)
	replay, err := s.PrepareParseOutput(t.Context(), a, output)
	require.NoError(t, err)
	require.Equal(t, upload.ID, replay.ID)
	changed := output
	changed.Storage = "object"
	_, err = s.PrepareParseOutput(t.Context(), a, changed)
	require.Equal(t, "IDEMPOTENCY_CONFLICT", reason(err))
	scope := OutputScope{Attempt: a, Stage: "parse", UploadID: upload.ID}
	_, err = s.GetUpload(ctx, fs, upload.ID)
	require.Equal(t, codes.NotFound, status.Code(err), "public upload API cannot read processing output")
	wrong := scope
	wrong.Stage = "enrichment"
	_, err = s.GetOutputUpload(t.Context(), wrong)
	require.Equal(t, "PARSE_NOT_COMPLETE", reason(err))
	wrong = scope
	wrong.Attempt.ID = uuid.New()
	_, err = s.WriteOutputBytes(t.Context(), wrong, []byte("abc"))
	require.Equal(t, "STALE_PROCESSING_ATTEMPT", reason(err))
	_, err = s.CompleteOutputUpload(t.Context(), scope, nil)
	require.Equal(t, "UPLOAD_NOT_READY", reason(err))
	_, err = s.WriteOutputBytes(t.Context(), scope, []byte{0, 255, 1})
	require.NoError(t, err)
	_, err = s.WriteOutputBytes(t.Context(), scope, []byte("abc"))
	require.Equal(t, "IDEMPOTENCY_CONFLICT", reason(err))
	receipt, err := s.CompleteOutputUpload(t.Context(), scope, nil)
	require.NoError(t, err)
	require.Equal(t, "finalized", receipt.State)
	_, err = s.CompleteOutputUpload(t.Context(), scope, nil)
	require.NoError(t, err)
	// Finalizing an output reserves no visible node or quota until the complete manifest commits.
	var used, beforeNodes int64
	require.NoError(t, db.QueryRow(t.Context(), `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.EqualValues(t, 3, used)
	require.NoError(t, db.QueryRow(t.Context(), `SELECT node_count FROM filesystems WHERE id=$1`, fs).Scan(&beforeNodes))
	manifest := ParseManifest{Uploads: []uuid.UUID{upload.ID}, Directories: []string{"empty", "pages"}}
	require.Equal(t, "OUTPUTS_INCOMPLETE", reason(s.CompleteParse(t.Context(), a, ParseManifest{})))
	require.Equal(t, "OUTPUTS_INCOMPLETE", reason(s.CompleteParse(t.Context(), a, ParseManifest{Uploads: []uuid.UUID{upload.ID, upload.ID}})))
	collision := manifest
	collision.Directories = []string{"pages/text.md"}
	require.Equal(t, codes.InvalidArgument, status.Code(s.CompleteParse(t.Context(), a, collision)))
	_, err = db.Exec(t.Context(), `UPDATE quota_buckets SET limit_bytes=used_bytes WHERE id=$1`, bucket)
	require.NoError(t, err)
	require.Equal(t, "QUOTA_EXCEEDED", reason(s.CompleteParse(t.Context(), a, manifest)))
	var children int64
	require.NoError(t, db.QueryRow(t.Context(), `SELECT count(*) FROM nodes WHERE parent_id=$1`, source.ID).Scan(&children))
	require.Zero(t, children)
	_, err = db.Exec(t.Context(), `UPDATE quota_buckets SET limit_bytes=1000 WHERE id=$1`, bucket)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `UPDATE filesystems SET max_nodes=node_count+2 WHERE id=$1`, fs)
	require.NoError(t, err)
	require.Equal(t, "RESOURCE_LIMIT", reason(s.CompleteParse(t.Context(), a, manifest)))
	require.NoError(t, db.QueryRow(t.Context(), `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.EqualValues(t, 3, used, "quota debit rolls back if node admission fails")
	_, err = db.Exec(t.Context(), `UPDATE filesystems SET max_nodes=100 WHERE id=$1`, fs)
	require.NoError(t, err)
	require.NoError(t, s.CompleteParse(t.Context(), a, manifest))
	require.NoError(t, s.CompleteParse(t.Context(), a, ParseManifest{Uploads: manifest.Uploads, Directories: []string{"pages", "empty"}}))
	require.Equal(t, "IDEMPOTENCY_CONFLICT", reason(s.CompleteParse(t.Context(), a, ParseManifest{Uploads: manifest.Uploads})))
	require.NoError(t, db.QueryRow(t.Context(), `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&used))
	require.EqualValues(t, 6, used)
	var count int64
	require.NoError(t, db.QueryRow(t.Context(), `SELECT node_count FROM filesystems WHERE id=$1`, fs).Scan(&count))
	require.Equal(t, beforeNodes+3, count)
	artifactPath := "/document.pdf/pages/text.md"
	artifact, err := s.GetNode(ctx, fs, mounts, Locator{Path: &artifactPath})
	require.NoError(t, err)
	require.Equal(t, "text/markdown", *artifact.MediaType)
	require.True(t, artifact.readonly)
	var content []byte
	require.NoError(t, db.QueryRow(t.Context(), `SELECT inline_bytes FROM files WHERE node_id=$1`, artifact.ID).Scan(&content))
	require.Equal(t, []byte{0, 255, 1}, content)
	var storedBytes []byte
	var published uuid.UUID
	require.NoError(t, db.QueryRow(t.Context(), `SELECT inline_bytes,result_node_id FROM uploads WHERE id=$1`, upload.ID).Scan(&storedBytes, &published))
	require.Nil(t, storedBytes)
	require.Equal(t, artifact.ID, published)
	_, err = s.WriteOutputBytes(t.Context(), scope, []byte{0, 255, 1})
	require.NoError(t, err, "lost acknowledgement can replay after publication without restoring upload bytes")
	// A replacement invalidates both a publication replay and its old upload handle.
	_, err = s.ReplaceContent(ctx, fs, mounts, Locator{NodeID: &source.ID}, &source.Revision, []byte("new"), "application/pdf")
	require.NoError(t, err)
	require.Equal(t, "SOURCE_REPLACED", reason(s.CompleteParse(t.Context(), a, manifest)))
	_, err = s.GetOutputUpload(t.Context(), scope)
	require.Equal(t, "SOURCE_REPLACED", reason(err))
}
