package storage

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"sync/atomic"
	"testing"

	"github.com/google/uuid"
	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/option"
	"github.com/qdrant/go-client/qdrant"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	"google.golang.org/grpc"
)

func TestQueryEmbeddingUsesFloatSpaceAndNativeCost(t *testing.T) {
	recorder := tracetest.NewSpanRecorder()
	provider := trace.NewTracerProvider(trace.WithSpanProcessor(recorder))
	previous := otel.GetTracerProvider()
	otel.SetTracerProvider(provider)
	defer otel.SetTracerProvider(previous)
	defer provider.Shutdown(context.Background())
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("baggage") != "" {
			t.Error("internal attribution must not reach the provider")
		}
		var input struct {
			Model      string `json:"model"`
			Dimensions int    `json:"dimensions"`
			Encoding   string `json:"encoding_format"`
		}
		if err := json.NewDecoder(r.Body).Decode(&input); err != nil {
			t.Error(err)
		}
		if input.Model != "embedding" || input.Dimensions != 3 || input.Encoding != "float" {
			t.Errorf("wrong embedding space: %+v", input)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("x-litellm-response-cost", "0")
		_, _ = w.Write([]byte(`{"data":[{"index":0,"embedding":[0.1,0.2,0.3]}],"usage":{"prompt_tokens":5,"total_tokens":5}}`))
	}))
	defer server.Close()
	s := Server{Models: openai.NewClient(option.WithBaseURL(server.URL), option.WithAPIKey("fixture"), option.WithMaxRetries(0)), EmbeddingModel: "embedding", EmbeddingDimensions: 3}
	id := uuid.NewString()
	ctx := propagation.Baggage{}.Extract(context.Background(), propagation.MapCarrier{"baggage": "langfuse_session_id=" + id + ",langfuse_metadata_agent_id=%22" + id + "%22"})
	vector, err := s.queryEmbedding(ctx, "query")
	if err != nil || len(vector) != 3 {
		t.Fatalf("embedding: %v %v", vector, err)
	}
	spans := recorder.Ended()
	if len(spans) != 1 {
		t.Fatalf("expected one embedding observation: %d", len(spans))
	}
	attrs := map[string]string{}
	for _, attr := range spans[0].Attributes() {
		attrs[string(attr.Key)] = attr.Value.Emit()
	}
	if attrs["session.id"] != id || attrs["langfuse.observation.metadata.agent_id"] != id {
		t.Fatalf("RAG attribution lost: %v", attrs)
	}
	if attrs["langfuse.observation.cost_details"] != `{"total":0}` || attrs["gen_ai.usage.input_tokens"] != "5" {
		t.Fatalf("cost and usage lost: %v", attrs)
	}
	if attrs["langfuse.observation.output"] != `{"count":1,"dimensions":3}` {
		t.Fatalf("unexpected output: %v", attrs)
	}
}

type fakeQdrantPoints struct {
	qdrant.UnimplementedPointsServer
	singleCalls atomic.Int32
	batchCalls  atomic.Int32
	batchSizes  []int
}

func (f *fakeQdrantPoints) Query(_ context.Context, r *qdrant.QueryPoints) (*qdrant.QueryResponse, error) {
	f.singleCalls.Add(1)
	return &qdrant.QueryResponse{
		Result: []*qdrant.ScoredPoint{{
			Id:    qdrant.NewIDNum(1),
			Score: 0.7,
			Payload: map[string]*qdrant.Value{
				"blob_id":       qdrant.NewValueString("single-blob"),
				"artifact_path": qdrant.NewValueString("01-part.md"),
				"text":          qdrant.NewValueString("hit"),
			},
		}},
	}, nil
}

func (f *fakeQdrantPoints) QueryBatch(_ context.Context, r *qdrant.QueryBatchPoints) (*qdrant.QueryBatchResponse, error) {
	f.batchCalls.Add(1)
	f.batchSizes = f.batchSizes[:0]
	results := make([]*qdrant.BatchResult, len(r.QueryPoints))
	for i, q := range r.QueryPoints {
		kw := q.Prefetch[0].Filter.Must[1].GetField().GetMatch().GetKeywords().GetStrings()
		f.batchSizes = append(f.batchSizes, len(kw))
		results[i] = &qdrant.BatchResult{
			Result: []*qdrant.ScoredPoint{{
				Id:    qdrant.NewIDNum(uint64(i + 1)),
				Score: float32(i+1) * 0.25,
				Payload: map[string]*qdrant.Value{
					"blob_id":       qdrant.NewValueString(kw[0]),
					"artifact_path": qdrant.NewValueString("01-part.md"),
					"text":          qdrant.NewValueString("chunk-" + strconv.Itoa(i)),
				},
			}},
		}
	}
	return &qdrant.QueryBatchResponse{Result: results}, nil
}

func TestQueryQdrantHybridChunksLargeBlobScopesViaQueryBatch(t *testing.T) {
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	stub := &fakeQdrantPoints{}
	srv := grpc.NewServer()
	qdrant.RegisterPointsServer(srv, stub)
	go srv.Serve(lis)
	defer srv.Stop()

	_, portStr, _ := net.SplitHostPort(lis.Addr().String())
	port, _ := strconv.Atoi(portStr)
	client, err := qdrant.NewClient(&qdrant.Config{
		Host:                   "127.0.0.1",
		Port:                   port,
		SkipCompatibilityCheck: true,
		PoolSize:               1,
	})
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()

	s := Server{Qdrant: client, Collection: "chunks"}
	ctx := context.Background()

	single, err := s.queryQdrantHybrid(ctx, "ws-1", []string{"b1"}, []float32{0.1, 0.2}, "q", 5, 2)
	if err != nil || len(single) != 1 || stub.singleCalls.Load() != 1 {
		t.Fatalf("small scope expected single Query: len=%d err=%v single=%d", len(single), err, stub.singleCalls.Load())
	}

	many := make([]string, 2500)
	for i := range many {
		many[i] = uuid.NewString()
	}
	batched, err := s.queryQdrantHybrid(ctx, "ws-1", many, []float32{0.1, 0.2}, "q", 10, 1)
	if err != nil {
		t.Fatalf("large scope batch query: %v", err)
	}
	if stub.batchCalls.Load() != 1 || len(stub.batchSizes) != 2 || stub.batchSizes[0] != 2000 || stub.batchSizes[1] != 500 {
		t.Fatalf("expected 2000+500 QueryBatch split, got calls=%d sizes=%v", stub.batchCalls.Load(), stub.batchSizes)
	}
	if len(batched) != 1 || batched[0].Payload["text"].GetStringValue() != "chunk-1" {
		t.Fatalf("expected merged top-1 highest score point from batch 1, got %+v", batched)
	}
}

func TestGlobAndGrepHelpers(t *testing.T) {
	if !hasHiddenSegment(".tool-output/run1.txt") || !hasHiddenSegment("a/.hidden/b") || hasHiddenSegment("reports/2025.csv") {
		t.Fatal("hasHiddenSegment mismatch")
	}
	if !matchesIncludeGlob("*.csv", "pack.pdf/tables/01.csv") || matchesIncludeGlob("*.md", "pack.pdf/tables/01.csv") {
		t.Fatal("matchesIncludeGlob mismatch")
	}
	if !matchesIncludeGlob("tables/*.csv", "tables/01.csv") || matchesIncludeGlob("tables/*.csv", "other/01.csv") {
		t.Fatal("matchesIncludeGlob path mismatch")
	}
	if _, ok := pgSafeRegex(`foo|bar[0-9]+`); !ok {
		t.Fatal("expected basic regex to be pg-safe")
	}
	if _, ok := pgSafeRegex(`\bword\b`); ok {
		t.Fatal("expected \\b regex to bypass pg pre-filter")
	}

	m, err := newLineMatcher(`rev\d+`, false, false)
	if err != nil {
		t.Fatal(err)
	}
	out := new(pb.GrepResponse)
	truncated := extractGrepLines("line1\nREV42 long line here\nrev99 second match\nrev100 third", "a/b.csv", "n1", "b.csv", m, 10, 2, out)
	if !truncated || len(out.Hits) != 2 {
		t.Fatalf("expected truncated=true len=2, got truncated=%v len=%d", truncated, len(out.Hits))
	}
	if out.Hits[0].LineNumber != 2 || out.Hits[0].LineText != "REV42 long" || out.Hits[1].LineNumber != 3 {
		t.Fatalf("unexpected hits: %+v", out.Hits)
	}
}
