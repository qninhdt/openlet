//go:build integration

package filesystem

import (
	"bytes"
	"context"
	"crypto/md5"
	"encoding/base64"
	"io"
	"net/http"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
)

func TestIntegrationParseObjectOutputsUseInternalEndpointAndFenceLateCompletion(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	endpoint := testfixture.S3(t)
	objects, err := storage.New(storage.Config{Endpoint: endpoint, SigningEndpoint: "https://public-storage.invalid", Region: "us-east-1", Bucket: "openlet-integration", AccessKey: "integration", SecretKey: "isolated-testcontainers-secret", AllowHTTP: true})
	require.NoError(t, err)
	s := Store{DB: db, Storage: objects, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 20 * 1024 * 1024,
		ProcessingMaxOutputs: 10, ProcessingMaxOutputBytes: 20 * 1024 * 1024, MultipartThreshold: 5 * 1024 * 1024, MultipartPartBytes: 5 * 1024 * 1024, UploadLifetime: time.Minute, UploadTransferGrace: time.Hour}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	bucket, fs, file := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = s.CreateBucket(owner, uuid.New(), CreateBucket{ID: bucket, LimitBytes: 20 * 1024 * 1024})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	// Seed only the canonical original; all output operations exercise the real pipeline store.
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
	put := func(transfer storage.SignedUpload, data []byte) string {
		t.Helper()
		require.Contains(t, transfer.URL, endpoint+"/")
		request, err := http.NewRequestWithContext(t.Context(), http.MethodPut, transfer.URL, bytes.NewReader(data))
		require.NoError(t, err)
		for key, value := range transfer.Headers {
			request.Header.Set(key, value)
		}
		response, err := http.DefaultClient.Do(request)
		require.NoError(t, err)
		_, readErr := io.Copy(io.Discard, response.Body)
		closeErr := response.Body.Close()
		require.NoError(t, readErr)
		require.NoError(t, closeErr)
		require.Equal(t, http.StatusOK, response.StatusCode)
		return response.Header.Get("ETag")
	}
	singleBytes := []byte("output content")
	size := int64(len(singleBytes))
	checksum := md5.Sum(singleBytes)
	md5value := base64.StdEncoding.EncodeToString(checksum[:])
	single, err := s.PrepareParseOutput(t.Context(), a, ProcessingOutput{Path: "text.md", Storage: "object", SizeBytes: &size, ContentMD5: &md5value})
	require.NoError(t, err)
	require.Equal(t, "single", single.Transport)
	require.NotNil(t, single.Transfer)
	put(*single.Transfer, singleBytes)
	singleScope := OutputScope{Source: a, Stage: "parse", UploadID: single.ID}
	_, err = s.WriteOutputBytes(t.Context(), singleScope, singleBytes)
	require.Equal(t, "DIRECT_UPLOAD_REQUIRED", reason(err))
	_, err = s.CompleteOutputUpload(t.Context(), singleScope, nil)
	require.NoError(t, err)
	multipartBytes := bytes.Repeat([]byte{0, 255, 7}, (5*1024*1024)/3+1)
	size = int64(len(multipartBytes))
	multi, err := s.PrepareParseOutput(t.Context(), a, ProcessingOutput{Path: "image.png", Storage: "object", SizeBytes: &size})
	require.NoError(t, err)
	require.Equal(t, "multipart", multi.Transport)
	require.EqualValues(t, 2, multi.PartCount())
	scope := OutputScope{Source: a, Stage: "parse", UploadID: multi.ID}
	parts, err := s.GetOutputUploadParts(t.Context(), scope, []int32{1, 2})
	require.NoError(t, err)
	receipts := make([]storage.PartReceipt, 0, 2)
	for _, part := range parts {
		start := int64(part.Number-1) * s.MultipartPartBytes
		end := min(start+s.MultipartPartBytes, size)
		receipts = append(receipts, storage.PartReceipt{Number: part.Number, ETag: put(part.Transfer, multipartBytes[start:end])})
	}
	finalized, err := s.CompleteOutputUpload(t.Context(), scope, receipts)
	require.NoError(t, err)
	require.Equal(t, "finalized", finalized.State)
	_, err = s.CompleteOutputUpload(t.Context(), scope, nil)
	require.NoError(t, err)
	mismatch := append([]storage.PartReceipt(nil), receipts...)
	mismatch[0].ETag = "different"
	_, err = s.CompleteOutputUpload(t.Context(), scope, mismatch)
	require.Equal(t, "IDEMPOTENCY_CONFLICT", reason(err))
	require.NoError(t, s.CompleteParse(t.Context(), a, ParseManifest{Uploads: []uuid.UUID{multi.ID}}))
	var queued bool
	require.NoError(t, db.QueryRow(t.Context(), `SELECT ambiguous_write FROM object_deletions WHERE object_key=$1`, *single.key).Scan(&queued))
	require.True(t, queued, "publication discards unused outputs from earlier work")
	var key string
	require.NoError(t, db.QueryRow(t.Context(), `SELECT f.object_key FROM uploads u JOIN files f ON f.node_id=u.result_node_id WHERE u.id=$1`, multi.ID).Scan(&key))
	reader, err := objects.Open(t.Context(), key)
	require.NoError(t, err)
	content, err := io.ReadAll(reader)
	require.NoError(t, err)
	require.NoError(t, reader.Close())
	require.Equal(t, multipartBytes, content)
	_, err = s.GetOutputUploadParts(t.Context(), scope, []int32{1})
	require.Equal(t, "UPLOAD_NOT_ACTIVE", reason(err))
	canceled, cancel := context.WithCancel(t.Context())
	cancel()
	_, err = s.GetOutputUpload(canceled, scope)
	require.ErrorIs(t, err, context.Canceled)
}
