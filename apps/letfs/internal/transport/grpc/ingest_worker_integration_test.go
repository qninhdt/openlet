//go:build integration

package grpc

import (
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/search"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	fstemporal "github.com/qninhdt/openlet/apps/letfs/internal/temporal"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"go.temporal.io/api/enums/v1"
	historypb "go.temporal.io/api/history/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/encoding/protojson"
)

func TestIntegrationPythonActivitiesProcessEnrichIndexAndReplay(t *testing.T) {
	db := testfixture.Postgres(t, "../../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../../packages/contracts/authz/schema.zed")
	tc, temporalAddress := sharedfixture.Temporal(t)
	endpoint := testfixture.S3(t)
	qdrant := testfixture.Qdrant(t)
	objects, err := storage.New(storage.Config{Endpoint: endpoint, Region: "us-east-1", Bucket: "openlet-integration", AccessKey: "integration", SecretKey: "isolated-testcontainers-secret", AllowHTTP: true})
	require.NoError(t, err)
	store := &filesystem.Store{DB: db, Graph: graph, Storage: objects, MaxNodes: 1000, InlineLimit: 65536, MaxFileBytes: 16 << 20,
		ProcessingMaxOutputs: 100, ProcessingMaxOutputBytes: 16 << 20, MultipartThreshold: 5 << 20, MultipartPartBytes: 5 << 20,
		MaxOutstanding: 100, MaxCleanupBacklog: 100, UploadLifetime: time.Minute, UploadTransferGrace: time.Hour, DownloadLifetime: time.Minute,
		IndexSpace: filesystem.VectorSpace{Model: "fixture-embedding", Collection: "files", Dimension: 2}}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	filesystemID, fs, file := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: filesystemID, LimitBytes: 32 << 20})
	require.NoError(t, err)
	created, err := createTestScope(owner, store, uuid.New(), filesystemID, fs)
	require.NoError(t, err)
	root, err := filepath.Abs("../../../../..")
	require.NoError(t, err)
	content, err := os.ReadFile(filepath.Join(root, "apps/letfs-ingest/tests/fixtures/image.docx"))
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'report.docx','file',$4)`, file, fs, created.RootID, len(content))
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_format,publication_status)
 VALUES($1,'inline',$2,1,'docx','pending')`, file, content)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `UPDATE filesystems SET node_count=2 WHERE id=$1`, filesystemID)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `UPDATE filesystems SET used_bytes=$2 WHERE id=$1`, filesystemID, len(content))
	require.NoError(t, err)
	const token = "isolated-python-ingest-token-1234567890"
	const gatewayToken = "isolated-python-search-gateway-token-1234567890"
	var methods []string
	for _, method := range letfsv1.IngestService_ServiceDesc.Methods {
		methods = append(methods, "/"+letfsv1.IngestService_ServiceDesc.ServiceName+"/"+method.MethodName)
	}
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{{Service: "ingest", Token: token, Methods: methods},
		{Service: "gateway", Token: gatewayToken, Gateway: true, Methods: []string{letfsv1.FilesystemService_SemanticSearch_FullMethodName}}})
	require.NoError(t, err)
	var acknowledgments sync.Map
	lostAcknowledgment := func(ctx context.Context, request any, info *grpcgo.UnaryServerInfo, handler grpcgo.UnaryHandler) (any, error) {
		response, err := handler(ctx, request)
		switch info.FullMethod {
		case letfsv1.IngestService_CompleteParse_FullMethodName, letfsv1.IngestService_CompleteEnrichment_FullMethodName, letfsv1.IngestService_CompleteIndex_FullMethodName:
			counter, _ := acknowledgments.LoadOrStore(info.FullMethod, &atomic.Int32{})
			if counter.(*atomic.Int32).Add(1) <= 3 && err == nil {
				return nil, status.Error(codes.Unavailable, "fixture lost committed acknowledgment")
			}
		}
		return response, err
	}
	server := grpcgo.NewServer(grpcgo.ChainUnaryInterceptor(authentication.Unary(), lostAcknowledgment))
	letfsv1.RegisterIngestServiceServer(server, &Ingest{Store: store})
	letfsv1.RegisterFilesystemServiceServer(server, &Filesystem{Store: store, Service: &filesystem.Service{Store: store}})
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	var descriptions, embeddings atomic.Int32
	var rerankUnavailable atomic.Bool
	provider := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if r.URL.Path == "/api/v1/embeddings" {
			var request struct{ Input json.RawMessage }
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				http.Error(w, "invalid fixture input", http.StatusBadRequest)
				return
			}
			var input []string
			if err := json.Unmarshal(request.Input, &input); err != nil {
				var single string
				if err := json.Unmarshal(request.Input, &single); err != nil {
					http.Error(w, "invalid fixture input", http.StatusBadRequest)
					return
				}
				input = []string{single}
			}
			embeddings.Add(1)
			data := make([]any, len(input))
			for i := range data {
				data[i] = map[string]any{"object": "embedding", "index": i, "embedding": []float64{1, 0}}
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"object": "list", "model": "fixture-embedding", "data": data, "usage": map[string]int{"prompt_tokens": 1, "total_tokens": 1}})
			return
		}
		if r.URL.Path == "/api/v1/rerank" {
			if rerankUnavailable.Load() {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			var request struct{ Documents []string }
			if err := json.NewDecoder(r.Body).Decode(&request); err != nil {
				http.Error(w, "invalid fixture input", http.StatusBadRequest)
				return
			}
			order := make([]int, len(request.Documents))
			for i := range order {
				order[i] = i
			}
			slices.SortFunc(order, func(a, b int) int { return len(request.Documents[b]) - len(request.Documents[a]) })
			results := make([]any, len(order))
			for i, index := range order {
				results[i] = map[string]any{"index": index, "relevance_score": float64(len(order) - i)}
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"model": "fixture-rerank", "results": results})
			return
		}
		if r.URL.Path != "/api/v1/chat/completions" {
			http.NotFound(w, r)
			return
		}
		descriptions.Add(1)
		metadata := `{"title":"Report","description":"A report with an image.","type":"document:report","context":"Evidence from the original report and its image."}`
		_ = json.NewEncoder(w).Encode(map[string]any{"id": "fixture", "object": "chat.completion", "created": 1, "model": "fixture-generation", "choices": []any{map[string]any{"index": 0, "finish_reason": "stop", "message": map[string]string{"role": "assistant", "content": metadata}}}})
	}))
	t.Cleanup(provider.Close)
	store.Search, err = search.New(qdrant, testfixture.QdrantKey)
	require.NoError(t, err)
	store.AI, err = search.NewAI(search.AIConfig{URL: provider.URL + "/api/v1", Key: "controlled-provider-token", RerankModel: "fixture-rerank", AllowLocal: true})
	require.NoError(t, err)
	goWorker := worker.New(tc, fstemporal.Queue, worker.Options{WorkerStopTimeout: time.Second})
	fstemporal.Register(goWorker, &fstemporal.Activities{Store: store})
	require.NoError(t, goWorker.Start())
	t.Cleanup(goWorker.Stop)
	ctx, cancel := context.WithTimeout(t.Context(), 3*time.Minute)
	defer cancel()
	id := "python-processing/" + file.String()
	run, err := tc.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: id, TaskQueue: fstemporal.Queue}, fstemporal.ProcessFileName,
		fstemporal.ProcessFileInput{Source: filesystem.Generation{FileID: file, Generation: 1}, ParseRequired: true, EnrichmentRequired: true})
	require.NoError(t, err)
	command := exec.CommandContext(ctx, "uv", "run", "--locked", "--package", "letfs-ingest", "python", "apps/letfs-ingest/tests/ingest_worker.py")
	command.Dir = root
	// DOCX uses Docling's Word pipeline, which needs no downloaded PDF/OCR models.
	command.Env = append(os.Environ(), "OPENLET_TEST_TEMPORAL="+temporalAddress, "OPENLET_TEST_RPC="+listener.Addr().String(), "OPENLET_TEST_INGEST_TOKEN="+token,
		"OPENLET_TEST_MODELS="+t.TempDir(), "OPENLET_TEST_FILE="+file.String(), "OPENLET_TEST_WORKFLOW="+id, "OPENLET_TEST_PROVIDER="+provider.URL, "OPENLET_TEST_QDRANT="+qdrant)
	output, err := command.CombinedOutput()
	require.NoError(t, err, "%s", output)
	require.Contains(t, string(output), "native-python-activities-ok")
	var result filesystem.Generation
	require.NoError(t, run.Get(ctx, &result))
	require.Equal(t, filesystem.Generation{FileID: file, Generation: 1}, result)
	var publication string
	require.NoError(t, db.QueryRow(ctx, `SELECT publication_status FROM files WHERE node_id=$1`, file).Scan(&publication))
	require.Equal(t, "ready", publication)
	var key string
	require.NoError(t, db.QueryRow(ctx, `SELECT f.object_key FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.parent_id=$1 AND f.media_type='image/png'`, file).Scan(&key))
	image, err := objects.Open(ctx, key)
	require.NoError(t, err)
	png, err := io.ReadAll(image)
	require.NoError(t, err)
	require.NoError(t, image.Close())
	require.True(t, len(png) > 8)
	require.Equal(t, "\x89PNG\r\n\x1a\n", string(png[:8]))
	require.GreaterOrEqual(t, descriptions.Load(), int32(2))
	require.Positive(t, embeddings.Load())
	actor := uuid.New()
	testfixture.Grant(t, graph, "scope", fs, actor, authz.ScopeReadContent)
	connection, err := grpcgo.NewClient(listener.Addr().String(), grpcgo.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	caller := metadata.NewOutgoingContext(ctx, metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-user-id", actor.String()))
	public := letfsv1.NewFilesystemServiceClient(connection)
	query := &letfsv1.SemanticSearchRequest{FilesystemId: filesystemID.String(), ScopeId: fs.String(), Query: "image"}
	page, err := public.SemanticSearch(caller, query)
	require.NoError(t, err)
	require.Len(t, page.Items, 1)
	require.Equal(t, file.String(), page.Items[0].Node.Id, "generated evidence groups into its original")
	require.NotEqual(t, file.String(), page.Items[0].Matched.FileId, "rerank selects the longer generated evidence")
	require.Equal(t, file.String(), page.Items[0].Matched.Breadcrumb[0].NodeId)
	require.Nil(t, page.Items[0].Node.Context)
	require.False(t, page.Degraded)
	rerankUnavailable.Store(true)
	page, err = public.SemanticSearch(caller, query)
	require.NoError(t, err)
	require.Len(t, page.Items, 1)
	require.True(t, page.Degraded)
	require.Equal(t, "RERANK_UNAVAILABLE", page.GetDegradedReason())
	acknowledgments.Range(func(_, value any) bool {
		require.EqualValues(t, 3, value.(*atomic.Int32).Load(), "RPC retries exhaust after commit; the next activity attempt prepares the completed result")
		return true
	})
	for _, scenario := range []struct {
		id     string
		stages []string
	}{{id, []string{"process_file", "enrich_file", "index_file"}}, {id + "-index-only", []string{"index_file"}}} {
		history := &historypb.History{}
		iterator := tc.GetWorkflowHistory(ctx, scenario.id, "", false, enums.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
		var stages []string
		var attempts []int32
		for iterator.HasNext() {
			event, err := iterator.Next()
			require.NoError(t, err)
			history.Events = append(history.Events, event)
			if scheduled := event.GetActivityTaskScheduledEventAttributes(); scheduled != nil {
				stages = append(stages, scheduled.ActivityType.Name)
			}
			if started := event.GetActivityTaskStartedEventAttributes(); started != nil {
				attempts = append(attempts, started.Attempt)
			}
		}
		require.Equal(t, scenario.stages, stages)
		if scenario.id == id {
			require.Equal(t, []int32{2, 2, 2}, attempts, "each real Python activity reconciles its committed result after Temporal retries")
		} else {
			require.Equal(t, []int32{1}, attempts)
		}
		replayer := worker.NewWorkflowReplayer()
		replayer.RegisterWorkflowWithOptions(fstemporal.ProcessFile, workflow.RegisterOptions{Name: fstemporal.ProcessFileName})
		require.NoError(t, replayer.ReplayWorkflowHistory(nil, history))
		if dir := os.Getenv("OPENLET_HISTORY_DIR"); dir != "" {
			require.NoError(t, os.MkdirAll(dir, 0o700))
			data, err := protojson.MarshalOptions{Indent: "  "}.Marshal(history)
			require.NoError(t, err)
			require.NoError(t, os.WriteFile(filepath.Join(dir, "ProcessFilePython-"+filepath.Base(scenario.id)+".json"), data, 0o600))
		}
	}
}
