//go:build integration

package filesystem

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"openlet/apps/letfs/internal/search"
	"openlet/apps/letfs/internal/testfixture"
	"openlet/packages/go/identity"
)

func TestIntegrationIndexCleanupExactScopeAndRebuildSerialization(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	endpoint := testfixture.Qdrant(t)
	provider, err := search.New(endpoint, testfixture.QdrantKey)
	require.NoError(t, err)
	s := Store{DB: db, Search: provider, MaxNodes: 100, ProcessingMaxOutputs: 10, IndexSpace: VectorSpace{Model: "embedding", Collection: "files", Dimension: 2}}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	bucket, fs, file := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = s.CreateBucket(owner, uuid.New(), CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'notes.txt','file',1)`, file, fs, created.RootID)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_format,publication_status)
 VALUES($1,'inline','x',1,'text','index_failed')`, file)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO index_deletions(file_id,generation) VALUES($1,1)`, file)
	require.NoError(t, err)
	request := func(method, path string, body any) map[string]json.RawMessage {
		t.Helper()
		data, err := json.Marshal(body)
		require.NoError(t, err)
		req, err := http.NewRequestWithContext(t.Context(), method, endpoint+path, bytes.NewReader(data))
		require.NoError(t, err)
		req.Header.Set("api-key", testfixture.QdrantKey)
		req.Header.Set("Content-Type", "application/json")
		response, err := (&http.Client{Timeout: 5 * time.Second}).Do(req)
		require.NoError(t, err)
		defer response.Body.Close()
		payload, err := io.ReadAll(response.Body)
		require.NoError(t, err)
		require.GreaterOrEqual(t, response.StatusCode, 200, "%s", payload)
		require.Less(t, response.StatusCode, 300, "%s", payload)
		var result map[string]json.RawMessage
		require.NoError(t, json.Unmarshal(payload, &result))
		return result
	}
	request("PUT", "/collections/files", map[string]any{"vectors": map[string]any{"dense": map[string]any{"size": 2, "distance": "Cosine"}}})
	target := uuid.NewString()
	points := []map[string]any{}
	for i := range 5 {
		payload := map[string]any{"source_id": file.String(), "generation": 1, "embedding_model": "embedding", "vector_dimension": 2}
		id := uuid.NewString()
		switch i {
		case 0:
			id = target
		case 1:
			payload["source_id"] = uuid.NewString()
		case 2:
			payload["generation"] = 2
		case 3:
			payload["embedding_model"] = "different-model"
		case 4:
			payload["vector_dimension"] = 3
		}
		points = append(points, map[string]any{"id": id, "vector": map[string]any{"dense": []int{1, 0}}, "payload": payload})
	}
	request("PUT", "/collections/files/points?wait=true", map[string]any{"points": points})
	items, err := s.IndexDeletionCandidates(t.Context())
	require.NoError(t, err)
	require.Len(t, items, 1)
	item := items[0]
	entered, release := make(chan struct{}), make(chan struct{})
	var released sync.Once
	destination, err := url.Parse(endpoint)
	require.NoError(t, err)
	forward := httputil.NewSingleHostReverseProxy(destination)
	delayed := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		close(entered)
		select {
		case <-release:
			forward.ServeHTTP(w, r)
		case <-r.Context().Done():
		}
	}))
	defer func() {
		released.Do(func() { close(release) })
		delayed.Close()
	}()
	s.Search, err = search.New(delayed.URL, testfixture.QdrantKey)
	require.NoError(t, err)
	type deletionResult struct {
		deleted bool
		err     error
	}
	deletion := make(chan deletionResult, 1)
	go func() {
		deleted, err := s.DeleteObsoleteIndex(t.Context(), item)
		deletion <- deletionResult{deleted, err}
	}()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("cleanup never reached Qdrant")
	}
	prepared := make(chan error, 1)
	go func() {
		_, err := s.PrepareIndex(t.Context(), item.Source)
		prepared <- err
	}()
	require.Eventually(t, func() bool {
		var waiting bool
		err := db.QueryRow(t.Context(), `SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND query LIKE '%quota_buckets%')`).Scan(&waiting)
		return err == nil && waiting
	}, 2*time.Second, 10*time.Millisecond, "new index admission waits for the cleanup lifecycle lock")
	released.Do(func() { close(release) })
	result := <-deletion
	require.NoError(t, result.err)
	require.True(t, result.deleted)
	require.NoError(t, <-prepared)
	var scroll struct {
		Points []struct {
			ID string `json:"id"`
		} `json:"points"`
	}
	response := request("POST", "/collections/files/points/scroll", map[string]any{"limit": 10})
	require.NoError(t, json.Unmarshal(response["result"], &scroll))
	require.Len(t, scroll.Points, 4, "cleanup removes only exact file/generation/model/dimension")
	for _, point := range scroll.Points {
		require.NotEqual(t, target, point.ID)
	}
	request("PUT", "/collections/files/points?wait=true", map[string]any{"points": points[:1]})
	require.NoError(t, s.CompleteIndex(t.Context(), item.Source))
	s.Search = provider
	deleted, err := s.DeleteObsoleteIndex(t.Context(), item)
	require.NoError(t, err)
	require.False(t, deleted, "a stale cleanup candidate cannot delete a newly current index")
	response = request("POST", "/collections/files/points/scroll", map[string]any{"limit": 10})
	require.NoError(t, json.Unmarshal(response["result"], &scroll))
	require.Len(t, scroll.Points, 5)
	var retained bool
	require.NoError(t, db.QueryRow(t.Context(), `SELECT eligible_at>now()+interval '23 hours' FROM index_deletions WHERE file_id=$1`, file).Scan(&retained))
	require.True(t, retained, "successful cleanup retains the tombstone for late obsolete upserts")
	items, err = s.IndexDeletionCandidates(t.Context())
	require.NoError(t, err)
	require.Empty(t, items)
	canceled, cancel := context.WithCancel(t.Context())
	cancel()
	_, err = s.DeleteObsoleteIndex(canceled, item)
	require.Error(t, err)
}
