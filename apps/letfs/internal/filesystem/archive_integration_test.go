//go:build integration

package filesystem

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/md5"
	"encoding/base64"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"golang.org/x/sync/semaphore"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestIntegrationArchiveExactBytesBoundsAndOwnedCancellation(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	endpoint := testfixture.S3(t)
	storageConfig := storage.Config{Endpoint: endpoint, Region: "us-east-1", Bucket: "openlet-integration", AccessKey: "integration", SecretKey: "isolated-testcontainers-secret", AllowHTTP: true}
	objects, err := storage.New(storageConfig)
	require.NoError(t, err)
	config := ArchiveConfig{MaxEntries: 10, MaxSourceBytes: 1000000, MaxOutputBytes: 2000000, Runtime: 5 * time.Second}
	s := Store{DB: db, Graph: graph, Storage: objects, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 1000000, Archive: config, ArchiveSlots: semaphore.NewWeighted(1)}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	bucket, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = s.CreateBucket(owner, uuid.New(), CreateBucket{ID: bucket, LimitBytes: 1000000})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, BucketID: bucket, RootName: "Báo cáo"})
	require.NoError(t, err)
	mounts := []Mount{{Path: "/drive", FilesystemID: fs}}
	_, err = s.OpenArchive(ctx, fs, mounts, *created.RootID)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	testfixture.Grant(t, graph, "filesystem", fs, actor, authz.Archive, authz.NodeCreate)
	inline, err := s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: "inline.txt", File: &InlineFile{Content: []byte("exact inline"), MediaType: "text/plain"}})
	require.NoError(t, err)
	_, err = s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: "empty"})
	require.NoError(t, err)
	object := uuid.New()
	payload := bytes.Repeat([]byte{0, 255, 17, 93}, 70000)
	digest := md5.Sum(payload)
	put, err := objects.SignPut(ctx, "archive/source", int64(len(payload)), base64.StdEncoding.EncodeToString(digest[:]), time.Minute)
	require.NoError(t, err)
	request, err := http.NewRequestWithContext(ctx, "PUT", put.URL, bytes.NewReader(payload))
	require.NoError(t, err)
	for key, value := range put.Headers {
		request.Header.Set(key, value)
	}
	response, err := (&http.Client{Timeout: 10 * time.Second}).Do(request)
	require.NoError(t, err)
	require.NoError(t, response.Body.Close())
	require.Equal(t, http.StatusOK, response.StatusCode)
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'object.bin','file',$4)`, object, fs, created.RootID, len(payload))
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,object_key) VALUES($1,'object','archive/source')`, object)
	require.NoError(t, err)
	generated := uuid.New()
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind) VALUES($1,$2,$3,'README.md','file')`, generated, fs, object)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,inline_bytes) VALUES($1,'inline','must not appear')`, generated)
	require.NoError(t, err)
	var before int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&before))
	stream, err := s.OpenArchive(ctx, fs, mounts, *created.RootID)
	require.NoError(t, err)
	require.Equal(t, "Báo cáo.zip", stream.Name)
	_, err = s.OpenArchive(ctx, fs, mounts, *created.RootID)
	require.Equal(t, codes.ResourceExhausted, status.Code(err))
	data, err := io.ReadAll(stream)
	require.NoError(t, err)
	require.NoError(t, stream.Close())
	archive, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	require.NoError(t, err)
	contents := map[string][]byte{}
	for _, file := range archive.File {
		reader, err := file.Open()
		require.NoError(t, err)
		contents[file.Name], err = io.ReadAll(reader)
		require.NoError(t, reader.Close())
		require.NoError(t, err)
	}
	require.Equal(t, map[string][]byte{"empty/": {}, "inline.txt": []byte("exact inline"), "object.bin": payload}, contents)
	var after int64
	require.NoError(t, db.QueryRow(ctx, `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucket).Scan(&after))
	require.Equal(t, before, after, "ZIP has no quota or stored-object side effects")
	for _, limit := range []ArchiveConfig{
		{MaxEntries: 1, MaxSourceBytes: config.MaxSourceBytes, MaxOutputBytes: config.MaxOutputBytes, Runtime: time.Second},
		{MaxEntries: 10, MaxSourceBytes: 1, MaxOutputBytes: config.MaxOutputBytes, Runtime: time.Second},
	} {
		s.Archive = limit
		_, err = s.OpenArchive(ctx, fs, mounts, *created.RootID)
		require.Equal(t, codes.ResourceExhausted, status.Code(err))
	}
	s.Archive = config
	s.Archive.MaxOutputBytes = 50
	stream, err = s.OpenArchive(ctx, fs, mounts, *created.RootID)
	require.NoError(t, err)
	_, err = io.ReadAll(stream)
	require.Error(t, err)
	require.NoError(t, stream.Close())
	s.Archive = config
	plan, err := s.preflightArchive(ctx, fs, mounts, *created.RootID)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE nodes SET revision=revision+1 WHERE id=$1`, inline.ID)
	require.NoError(t, err)
	err = s.produceArchive(ctx, plan, io.Discard)
	require.Equal(t, codes.Aborted, status.Code(err), "changed revision after preflight must fail")
	for _, collision := range []string{"INLINE.txt", "CON.txt"} {
		node, err := s.CreateNode(ctx, fs, mounts, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: collision, File: &InlineFile{Content: []byte("x"), MediaType: "text/plain"}})
		require.NoError(t, err)
		_, err = s.OpenArchive(ctx, fs, mounts, *created.RootID)
		require.Equal(t, codes.InvalidArgument, status.Code(err))
		_, err = db.Exec(ctx, `DELETE FROM files WHERE node_id=$1`, node.ID)
		require.NoError(t, err)
		_, err = db.Exec(ctx, `DELETE FROM nodes WHERE id=$1`, node.ID)
		require.NoError(t, err)
	}
	for _, timeout := range []bool{false, true} {
		entered, stopped := make(chan struct{}), make(chan struct{})
		var enterOnce, stopOnce sync.Once
		blocked := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			enterOnce.Do(func() { close(entered) })
			<-r.Context().Done()
			stopOnce.Do(func() { close(stopped) })
		}))
		storageConfig.Endpoint = blocked.URL
		s.Storage, err = storage.New(storageConfig)
		require.NoError(t, err)
		requestCtx, cancel := context.WithCancel(ctx)
		if timeout {
			s.Archive.Runtime = time.Second
		}
		stream, err = s.OpenArchive(requestCtx, fs, mounts, *created.RootID)
		require.NoError(t, err)
		completed := make(chan error, 1)
		go func() { _, err := io.Copy(io.Discard, stream); completed <- err }()
		select {
		case <-entered:
		case <-time.After(3 * time.Second):
			cancel()
			blocked.CloseClientConnections()
			t.Fatal("archive never opened the source object")
		}
		if !timeout {
			cancel()
		}
		select {
		case err := <-completed:
			require.Error(t, err)
		case <-time.After(3 * time.Second):
			cancel()
			blocked.CloseClientConnections()
			t.Fatal("archive ignored cancellation/deadline")
		}
		require.NoError(t, stream.Close())
		cancel()
		select {
		case <-stopped:
		case <-time.After(time.Second):
			blocked.CloseClientConnections()
			t.Fatal("active S3 request did not stop")
		}
		blocked.Close()
		require.True(t, s.ArchiveSlots.TryAcquire(1), "closing the stream releases its permit after the producer stops")
		s.ArchiveSlots.Release(1)
	}
}
