package storage

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/google/uuid"
	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/option"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
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
