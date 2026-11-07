//go:build integration

package filesystem

import (
	"bytes"
	"crypto/md5"
	"encoding/base64"
	"io"
	"net/http"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
)

func TestIntegrationMaintenanceProtectsReferencesAndRetainsAmbiguousCleanup(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	endpoint := testfixture.S3(t)
	objects, err := storage.New(storage.Config{Endpoint: endpoint, SigningEndpoint: endpoint, Region: "us-east-1",
		Bucket: "openlet-integration", AccessKey: "integration", SecretKey: "isolated-testcontainers-secret", AllowHTTP: true})
	require.NoError(t, err)
	s := Store{DB: db, Storage: objects, MaxNodes: 100}
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	filesystemID, fs, actor := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.New()
	_, err = s.CreateFilesystem(ctx, uuid.New(), CreateFilesystem{ID: filesystemID, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := createTestScope(ctx, &s, uuid.New(), filesystemID, fs)
	require.NoError(t, err)
	httpClient := &http.Client{Timeout: 10 * time.Second}
	put := func(key string) {
		t.Helper()
		data := []byte("payload")
		digest := md5.Sum(data)
		signed, err := objects.SignPut(ctx, key, int64(len(data)), base64.StdEncoding.EncodeToString(digest[:]), time.Minute)
		require.NoError(t, err)
		request, err := http.NewRequestWithContext(ctx, http.MethodPut, signed.URL, bytes.NewReader(data))
		require.NoError(t, err)
		for name, value := range signed.Headers {
			request.Header.Set(name, value)
		}
		response, err := httpClient.Do(request)
		require.NoError(t, err)
		_, err = io.Copy(io.Discard, response.Body)
		require.NoError(t, err)
		require.NoError(t, response.Body.Close())
		require.Equal(t, http.StatusOK, response.StatusCode)
	}
	for _, key := range []string{"cleanup/orphan", "cleanup/ambiguous", "cleanup/live", "cleanup/open"} {
		put(key)
		writes := 0
		if key == "cleanup/ambiguous" {
			writes = 1
		}
		_, err = db.Exec(ctx, `INSERT INTO object_deletions(object_key,filesystem_id,eligible_at,ambiguous_write,open_writes)
 VALUES($1,$2,now()-interval '1 second',$3,$4)`, key, filesystemID, key == "cleanup/ambiguous", writes)
		require.NoError(t, err)
	}
	file := uuid.Must(uuid.NewV7())
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind) VALUES($1,$2,$3,'live.bin','file')`, file, fs, created.RootID)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO files(node_id,storage_kind,object_key,media_type) VALUES($1,'object','cleanup/live','application/octet-stream')`, file)
	require.NoError(t, err)
	open := uuid.New()
	_, err = db.Exec(ctx, `INSERT INTO uploads(id,scope_id,actor_id,input,candidate_key,transport,expected_size,content_md5)
 VALUES($1,$2,$3,'{}','cleanup/open','single',7,'Mhw89IbtUJFk7eweGYH+yA==')`, open, fs, actor)
	require.NoError(t, err)
	count, err := s.DeleteObjects(ctx)
	require.NoError(t, err)
	require.Equal(t, 2, count)
	for _, key := range []string{"cleanup/orphan", "cleanup/ambiguous"} {
		_, err = objects.Head(ctx, key)
		require.ErrorIs(t, err, storage.ErrNotFound)
	}
	for _, key := range []string{"cleanup/live", "cleanup/open"} {
		_, err = objects.Head(ctx, key)
		require.NoError(t, err)
	}
	var state string
	var ambiguous bool
	var writes int64
	require.NoError(t, db.QueryRow(ctx, `SELECT state,ambiguous_write,open_writes FROM object_deletions WHERE object_key='cleanup/ambiguous'`).Scan(&state, &ambiguous, &writes))
	require.Equal(t, "deleted", state)
	require.True(t, ambiguous)
	require.EqualValues(t, 1, writes)
	// A write completing after the first DELETE is still covered by retained evidence.
	put("cleanup/ambiguous")
	_, err = db.Exec(ctx, `UPDATE object_deletions SET eligible_at=now()-interval '1 second' WHERE object_key='cleanup/ambiguous'`)
	require.NoError(t, err)
	count, err = s.DeleteObjects(ctx)
	require.NoError(t, err)
	require.Equal(t, 1, count)
	_, err = objects.Head(ctx, "cleanup/ambiguous")
	require.ErrorIs(t, err, storage.ErrNotFound)
	// Expiration keeps write grace and cleans provider multipart state after commit.
	remote, err := objects.CreateMultipart(ctx, "cleanup/multipart")
	require.NoError(t, err)
	multipart, inline := uuid.New(), uuid.New()
	_, err = db.Exec(ctx, `INSERT INTO uploads(id,scope_id,actor_id,input,candidate_key,transport,expected_size,multipart_id,part_size,expires_at)
 VALUES($1,$2,$3,'{}','cleanup/multipart','multipart',5242880,$4,5242880,now()-interval '1 second')`, multipart, fs, actor, remote)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `INSERT INTO uploads(id,scope_id,actor_id,input,transport,expected_size,inline_bytes,state,expires_at)
 VALUES($1,$2,$3,'{}','inline',7,'payload','completing',now()-interval '1 second')`, inline, fs, actor)
	require.NoError(t, err)
	_, err = db.Exec(ctx, `UPDATE uploads SET expires_at=now()-interval '1 second',transfer_deadline=now()+interval '1 hour' WHERE id=$1`, open)
	require.NoError(t, err)
	count, err = s.ExpireUploads(ctx)
	require.NoError(t, err)
	require.Equal(t, 3, count)
	var remaining int
	require.NoError(t, db.QueryRow(ctx, `SELECT count(*) FROM uploads WHERE id=ANY($1) AND state='aborted' AND inline_bytes IS NULL AND multipart_id IS NULL`, []uuid.UUID{open, multipart, inline}).Scan(&remaining))
	require.Equal(t, 3, remaining)
	var delayed bool
	require.NoError(t, db.QueryRow(ctx, `SELECT ambiguous_write AND eligible_at>=now()+interval '59 minutes' FROM object_deletions WHERE object_key='cleanup/open'`).Scan(&delayed))
	require.True(t, delayed)
	count, err = s.ExpireUploads(ctx)
	require.NoError(t, err)
	require.Zero(t, count)
	count, err = s.DeleteObjects(ctx)
	require.NoError(t, err)
	require.Zero(t, count)
	_, err = objects.Head(ctx, "cleanup/open")
	require.NoError(t, err)
}
