package search

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"google.golang.org/grpc/codes"
)

type Client struct {
	url, key string
	http     *http.Client
}

func Dependency() error {
	return rpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "search dependency unavailable")
}

func New(endpoint, key string) (*Client, error) {
	parsed, err := url.Parse(endpoint)
	if err != nil || parsed.Hostname() == "" || parsed.Scheme != "https" && parsed.Scheme != "http" || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || strings.TrimSpace(key) == "" || strings.ContainsAny(key, "\r\n") {
		return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid Qdrant configuration")
	}
	return &Client{url: strings.TrimRight(endpoint, "/"), key: key, http: &http.Client{Transport: otelhttp.NewTransport(http.DefaultTransport), Timeout: 5 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}, nil
}

func (c *Client) DeletePoints(ctx context.Context, collection string, source uuid.UUID, generation int64, model string, dimension int32) error {
	filter := make([]any, 0, 4)
	for _, field := range []struct {
		key   string
		value any
	}{{"source_id", source.String()}, {"generation", generation}, {"embedding_model", model}, {"vector_dimension", dimension}} {
		filter = append(filter, map[string]any{"key": field.key, "match": map[string]any{"value": field.value}})
	}
	body, err := json.Marshal(map[string]any{"filter": map[string]any{"must": filter}})
	if err != nil {
		return Dependency()
	}
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.url+"/collections/"+url.PathEscape(collection)+"/points/delete?wait=true", bytes.NewReader(body))
	if err != nil {
		return Dependency()
	}
	request.Header.Set("api-key", c.key)
	request.Header.Set("Content-Type", "application/json")
	response, err := c.http.Do(request)
	if err != nil {
		return Dependency()
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusNotFound {
		return nil
	}
	if response.StatusCode < 200 || response.StatusCode > 299 {
		return Dependency()
	}
	var result struct {
		Result struct {
			Status string `json:"status"`
		} `json:"result"`
	}
	if json.NewDecoder(io.LimitReader(response.Body, 1048576)).Decode(&result) != nil || result.Result.Status != "completed" {
		return Dependency()
	}
	return nil
}
