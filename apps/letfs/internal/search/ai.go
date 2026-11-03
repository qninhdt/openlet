package search

import (
	"context"
	"math"
	"net/http"
	"net/url"
	"strings"
	"time"

	openrouter "github.com/OpenRouterTeam/go-sdk"
	"github.com/OpenRouterTeam/go-sdk/models/operations"
	"github.com/OpenRouterTeam/go-sdk/retry"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"google.golang.org/grpc/codes"
)

type AIConfig struct {
	URL, Key, RerankModel string
	AllowLocal            bool
}

type AI struct {
	client      *openrouter.OpenRouter
	RerankModel string
}

func NewAI(config AIConfig) (*AI, error) {
	parsed, err := url.Parse(config.URL)
	if err != nil || parsed.Hostname() == "" || parsed.Scheme != "https" && !(parsed.Scheme == "http" && config.AllowLocal) || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || strings.TrimSpace(config.Key) == "" || strings.ContainsAny(config.Key, "\r\n") || strings.TrimSpace(config.RerankModel) == "" {
		return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid AI search configuration")
	}
	client := openrouter.New(
		openrouter.WithServerURL(strings.TrimRight(config.URL, "/")),
		openrouter.WithSecurity(config.Key),
		openrouter.WithClient(&http.Client{Transport: otelhttp.NewTransport(http.DefaultTransport),
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}),
		openrouter.WithTimeout(15*time.Second),
		// Interactive search keeps a finite provider budget without retrying paid requests.
		openrouter.WithRetryConfig(retry.Config{Strategy: "none"}),
	)
	return &AI{client: client, RerankModel: config.RerankModel}, nil
}

func (a *AI) Embed(ctx context.Context, query, model string, dimension int32) ([]float64, error) {
	response, err := a.client.Embeddings.Generate(ctx, operations.CreateEmbeddingsRequest{
		Model:          model,
		Input:          operations.CreateInputUnionStr(strings.TrimSpace(query)),
		Dimensions:     openrouter.Int64(int64(dimension)),
		EncodingFormat: operations.EncodingFormatFloat.ToPointer(),
	})
	if err != nil || response == nil || response.CreateEmbeddingsResponseBody == nil {
		return nil, Dependency()
	}
	data := response.CreateEmbeddingsResponseBody.Data
	if len(data) != 1 || len(data[0].Embedding.ArrayOfNumber) != int(dimension) {
		return nil, Dependency()
	}
	vector := data[0].Embedding.ArrayOfNumber
	for _, v := range vector {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return nil, Dependency()
		}
	}
	return vector, nil
}

func (a *AI) Rerank(ctx context.Context, query string, documents []string) ([]int, error) {
	input := make([]operations.Document, len(documents))
	for i, text := range documents {
		input[i] = operations.CreateDocumentStr(text)
	}
	response, err := a.client.Rerank.Rerank(ctx, operations.CreateRerankRequest{
		Model:     a.RerankModel,
		Query:     strings.TrimSpace(query),
		Documents: input,
		TopN:      openrouter.Int64(int64(len(documents))),
	})
	if err != nil || response == nil || response.CreateRerankResponseBody == nil || len(response.CreateRerankResponseBody.Results) != len(documents) {
		return nil, Dependency()
	}
	seen, order := make(map[int64]bool, len(documents)), make([]int, 0, len(documents))
	for _, row := range response.CreateRerankResponseBody.Results {
		if row.Index < 0 || row.Index >= int64(len(documents)) || seen[row.Index] || math.IsNaN(row.RelevanceScore) || math.IsInf(row.RelevanceScore, 0) {
			return nil, Dependency()
		}
		seen[row.Index] = true
		order = append(order, int(row.Index))
	}
	return order, nil
}
