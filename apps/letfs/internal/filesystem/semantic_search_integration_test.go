//go:build integration

package filesystem

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"io"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/search"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
)

func TestIntegrationSemanticSearchWithOpenRouterSDKAndCurrentFacts(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	endpoint := testfixture.Qdrant(t)
	qdrant, err := search.New(endpoint, testfixture.QdrantKey)
	require.NoError(t, err)
	s := Store{DB: db, Graph: graph, Search: qdrant, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 64,
		IndexSpace: VectorSpace{Model: "embedding-v1", Collection: "files", Dimension: 2}}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	actor := uuid.New()
	ctx := identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true, ActorID: actor})
	filesystemID, fs := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = s.CreateFilesystem(owner, uuid.New(), CreateFilesystem{ID: filesystemID, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := createTestScope(owner, &s, uuid.New(), filesystemID, fs)
	require.NoError(t, err)

	testfixture.Grant(t, graph, "scope", fs, actor, authz.ScopeWrite, authz.ScopeTrash, authz.ScopeReadContent)
	files := []Node{}
	for _, name := range []string{"A.txt", "B.txt", "not-ready.txt"} {
		node, err := s.CreateNode(ctx, fs, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: name,
			File: &InlineFile{Content: []byte("volcano"), MediaType: "text/plain"}})
		require.NoError(t, err)
		files = append(files, node)
	}
	for _, node := range files[:2] {
		_, err = db.Exec(ctx, `UPDATE files SET desired_generation=1,processing_format='text',publication_status='ready',context='private context' WHERE node_id=$1`, node.ID)
		require.NoError(t, err)
	}
	request := func(method, path string, body any) {
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
	}
	request("PUT", "/collections/files", map[string]any{"vectors": map[string]any{"dense": map[string]any{"size": 2, "distance": "Cosine"}}})
	request("PUT", "/collections/files/index?wait=true", map[string]any{"field_name": "text", "field_schema": map[string]any{"type": "text", "tokenizer": "word", "scoring": true}})
	points := []map[string]any{}
	point := func(source, file uuid.UUID, generation int64, model, text string, dimension int32) {
		points = append(points, map[string]any{"id": uuid.NewString(), "vector": map[string]any{"dense": []int{1, 0}},
			"payload": search.Payload{FilesystemID: filesystemID, ScopeID: fs, SourceID: source, FileID: file, Generation: generation, EmbeddingModel: model, VectorDimension: dimension, Text: text}})
	}
	point(files[0].ID, files[0].ID, 1, "embedding-v1", "volcano A", 2)
	point(files[0].ID, files[0].ID, 1, "embedding-v1", "volcano A duplicate evidence", 2)
	point(files[1].ID, files[1].ID, 1, "embedding-v1", "volcano B", 2)
	point(files[2].ID, files[2].ID, 1, "embedding-v1", "SECRET_NOT_READY volcano", 2)
	point(files[0].ID, files[0].ID, 2, "embedding-v1", "SECRET_GENERATION volcano", 2)
	point(files[0].ID, files[0].ID, 1, "different-model", "SECRET_MODEL volcano", 2)
	point(files[0].ID, files[0].ID, 1, "embedding-v1", "SECRET_DIMENSION volcano", 3)
	point(uuid.New(), files[1].ID, 1, "embedding-v1", "SECRET_ANCESTRY volcano", 2)
	request("PUT", "/collections/files/points?wait=true", map[string]any{"points": points})
	var embedFail, rerankFail atomic.Bool
	var mutation func()
	var mutationMu sync.Mutex
	var rerankDocuments []string
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		require.Equal(t, "Bearer isolated-key", r.Header.Get("Authorization"))
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/embeddings" {
			if embedFail.Load() {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			_, _ = fmt.Fprint(w, `{"object":"list","model":"embedding-v1","data":[{"object":"embedding","index":0,"embedding":[1,0]}]}`)
			return
		}
		require.Equal(t, "/rerank", r.URL.Path)
		var body struct {
			Documents []string `json:"documents"`
		}
		require.NoError(t, json.NewDecoder(r.Body).Decode(&body))
		for _, text := range body.Documents {
			require.NotContains(t, text, "SECRET_", "stale evidence must be excluded before reranking")
		}
		mutationMu.Lock()
		rerankDocuments = append([]string{}, body.Documents...)
		change := mutation
		mutation = nil
		mutationMu.Unlock()
		if change != nil {
			change()
		}
		if rerankFail.Load() {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		results := []map[string]any{}
		for i := len(body.Documents) - 1; i >= 0; i-- {
			results = append(results, map[string]any{"index": i, "relevance_score": float64(i)})
		}
		require.NoError(t, json.NewEncoder(w).Encode(map[string]any{"model": "rerank-v1", "results": results}))
	}))
	defer provider.Close()
	s.AI, err = search.NewAI(search.AIConfig{URL: provider.URL, Key: "isolated-key", RerankModel: "rerank-v1", AllowLocal: true})
	require.NoError(t, err)
	query := SearchInput{Query: "volcano"}
	page, err := s.SemanticSearch(ctx, fs, query)
	require.NoError(t, err)
	require.Len(t, page.Items, 2)
	require.False(t, page.Degraded)
	require.Nil(t, page.NextCursor)
	ids := []uuid.UUID{}
	for _, item := range page.Items {
		ids = append(ids, item.Node.ID)
		require.Equal(t, "/"+item.Node.Name, item.Path)
		require.Nil(t, item.Node.Context)
		require.NotNil(t, item.Matched)
		require.Contains(t, item.Matched.Snippet, "volcano")
		require.Equal(t, item.Node.ID, item.Matched.Breadcrumb[0].NodeID)
	}
	require.ElementsMatch(t, []uuid.UUID{files[0].ID, files[1].ID}, ids)
	mutationMu.Lock()
	require.Len(t, rerankDocuments, 3, "duplicate evidence is reranked but grouped into one original")
	mutationMu.Unlock()
	query.Limit = ptr(int32(1))
	first, err := s.SemanticSearch(ctx, fs, query)
	require.NoError(t, err)
	require.Len(t, first.Items, 1)
	require.NotNil(t, first.NextCursor)
	query.Cursor = first.NextCursor
	second, err := s.SemanticSearch(ctx, fs, query)
	require.NoError(t, err)
	require.Len(t, second.Items, 1)
	require.NotEqual(t, first.Items[0].Node.ID, second.Items[0].Node.ID)
	changed := query
	changed.Query = "different"
	_, err = s.SemanticSearch(ctx, fs, changed)
	require.Equal(t, apperr.Invalid, apperr.KindOf(err))
	originalModel := s.AI.RerankModel
	s.AI.RerankModel = "different-reranker"
	_, err = s.SemanticSearch(ctx, fs, query)
	require.Equal(t, apperr.Invalid, apperr.KindOf(err))
	s.AI.RerankModel = originalModel
	query.Cursor, query.Limit = nil, nil
	rerankFail.Store(true)
	page, err = s.SemanticSearch(ctx, fs, query)
	require.NoError(t, err)
	require.Len(t, page.Items, 2)
	require.True(t, page.Degraded)
	require.Equal(t, "RERANK_UNAVAILABLE", *page.DegradedReason)
	rerankFail.Store(false)
	embedFail.Store(true)
	_, err = s.SemanticSearch(ctx, fs, query)
	require.Equal(t, apperr.Unavailable, apperr.KindOf(err))
	embedFail.Store(false)
	working := s.Search
	s.Search, err = search.New(endpoint, "invalid-key")
	require.NoError(t, err)
	_, err = s.SemanticSearch(ctx, fs, query)
	require.Equal(t, apperr.Unavailable, apperr.KindOf(err))
	s.Search = working
	t.Run("bounded evidence and provider batches", func(t *testing.T) {
		original := points
		defer func() {
			s.Search = working
			request("POST", "/collections/files/points/delete?wait=true", map[string]any{"filter": map[string]any{"must": []any{}}})
			request("PUT", "/collections/files/points?wait=true", map[string]any{"points": original})
		}()
		remote, err := url.Parse(endpoint)
		require.NoError(t, err)
		forward := httputil.NewSingleHostReverseProxy(remote)
		var queries atomic.Int32
		proxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if strings.HasSuffix(r.URL.Path, "/points/query") {
				queries.Add(1)
			}
			forward.ServeHTTP(w, r)
		}))
		defer proxy.Close()
		s.Search, err = search.New(proxy.URL, testfixture.QdrantKey)
		require.NoError(t, err)
		request("POST", "/collections/files/points/delete?wait=true", map[string]any{"filter": map[string]any{"must": []any{}}})
		points = nil
		for i := range 300 {
			point(files[0].ID, files[0].ID, 1, "embedding-v1", fmt.Sprintf("volcano evidence %d", i), 2)
		}
		request("PUT", "/collections/files/points?wait=true", map[string]any{"points": points})
		bounded := SearchInput{Query: "volcano", Limit: ptr(int32(50))}
		page, err := s.SemanticSearch(ctx, fs, bounded)
		require.NoError(t, err)
		require.EqualValues(t, 3, queries.Load(), "one request reads at most three actual Qdrant batches")
		require.Len(t, page.Items, 1)
		require.NotNil(t, page.NextCursor)
		mutationMu.Lock()
		require.Len(t, rerankDocuments, 3, "one source contributes at most three evidence documents")
		rerankDocuments = nil
		mutationMu.Unlock()
		bounded.Cursor = page.NextCursor
		page, err = s.SemanticSearch(ctx, fs, bounded)
		require.NoError(t, err)
		require.Empty(t, page.Items, "a later page never repeats the original")
		require.Nil(t, page.NextCursor)
		mutationMu.Lock()
		require.Empty(t, rerankDocuments, "exhausted duplicate evidence needs no rerank")
		mutationMu.Unlock()
		request("POST", "/collections/files/points/delete?wait=true", map[string]any{"filter": map[string]any{"must": []any{}}})
		points = nil
		for i := range 30 {
			node, err := s.CreateNode(ctx, fs, uuid.New(), CreateNode{Parent: Locator{NodeID: created.RootID}, Name: fmt.Sprintf("bounded-%02d.txt", i),
				File: &InlineFile{Content: []byte("volcano"), MediaType: "text/plain"}})
			require.NoError(t, err)
			_, err = db.Exec(ctx, `UPDATE files SET desired_generation=1,processing_format='text',publication_status='ready' WHERE node_id=$1`, node.ID)
			require.NoError(t, err)
			for range 3 {
				point(node.ID, node.ID, 1, "embedding-v1", "volcano bounded evidence", 2)
			}
		}
		request("PUT", "/collections/files/points?wait=true", map[string]any{"points": points})
		queries.Store(0)
		bounded.Cursor = nil
		page, err = s.SemanticSearch(ctx, fs, bounded)
		require.NoError(t, err)
		require.EqualValues(t, 1, queries.Load(), "the evidence cap stops further provider batches")
		mutationMu.Lock()
		require.Len(t, rerankDocuments, 64, "rerank input stays bounded across many originals")
		mutationMu.Unlock()
		require.LessOrEqual(t, len(page.Items), 30)
		require.NotNil(t, page.NextCursor)
	})
	mutationMu.Lock()
	mutation = func() {
		_, err := s.TrashNode(ctx, fs, Locator{NodeID: &files[0].ID}, &files[0].Revision)
		require.NoError(t, err)
		_, err = db.Exec(ctx, `UPDATE files SET desired_generation=2,publication_status='pending' WHERE node_id=$1`, files[1].ID)
		require.NoError(t, err)
	}
	mutationMu.Unlock()
	page, err = s.SemanticSearch(ctx, fs, query)
	require.NoError(t, err)
	require.Empty(t, page.Items, "trash/replacement during rerank cannot return old evidence")
	_, err = db.Exec(ctx, `UPDATE files SET desired_generation=1,publication_status='ready' WHERE node_id=$1`, files[1].ID)
	require.NoError(t, err)
	mutationMu.Lock()
	mutation = func() {
		_, err := graph.DeleteRelationships(t.Context(), &v1.DeleteRelationshipsRequest{RelationshipFilter: &v1.RelationshipFilter{ResourceType: "scope", OptionalResourceId: fs.String()}})
		require.NoError(t, err)
	}
	mutationMu.Unlock()
	_, err = s.SemanticSearch(ctx, fs, query)
	require.Equal(t, apperr.Forbidden, apperr.KindOf(err), "revocation during rerank must be checked before returning text")
	_, err = s.SemanticSearch(context.Background(), fs, SearchInput{Query: strings.Repeat("a", 2001)})
	require.Equal(t, apperr.Unauthenticated, apperr.KindOf(err))
}
