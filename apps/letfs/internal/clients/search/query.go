package search

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"time"

	"github.com/google/uuid"
)

type Payload struct {
	ScopeID         uuid.UUID `json:"scope_id"`
	FilesystemID    uuid.UUID `json:"filesystem_id"`
	SourceID        uuid.UUID `json:"source_id"`
	FileID          uuid.UUID `json:"file_id"`
	Generation      int64     `json:"generation"`
	EmbeddingModel  string    `json:"embedding_model"`
	VectorDimension int32     `json:"vector_dimension"`
	Text            string    `json:"text"`
}

type Point struct {
	Payload Payload `json:"payload"`
}

func (c *Client) Query(ctx context.Context, collection string, fs, scope uuid.UUID, query string, vector []float64) ([]Point, error) {
	filter := map[string]any{"must": []any{map[string]any{"key": "filesystem_id", "match": map[string]any{"value": fs.String()}}, map[string]any{"key": "scope_id", "match": map[string]any{"value": scope.String()}}}}
	body := map[string]any{"prefetch": []any{
		map[string]any{"query": vector, "using": "dense", "filter": filter, "limit": 80},
		map[string]any{"query": map[string]any{"text": query}, "using": "text", "filter": filter, "limit": 80},
	}, "query": map[string]any{"fusion": "rrf"}, "limit": 80, "with_payload": true}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	// Query allows the reference 15-second provider budget; deletion remains capped at five seconds.
	httpClient := *c.http
	httpClient.Timeout = 15 * time.Second
	var response struct {
		Result struct {
			Points *[]Point `json:"points"`
		} `json:"result"`
	}
	err := postJSON(ctx, &httpClient, c.url+"/collections/"+url.PathEscape(collection)+"/points/query", "api-key", c.key, body, &response)
	if err != nil || response.Result.Points == nil || len(*response.Result.Points) > 80 {
		return nil, Dependency()
	}
	for _, point := range *response.Result.Points {
		p := point.Payload
		if p.FilesystemID == uuid.Nil || p.ScopeID == uuid.Nil || p.SourceID == uuid.Nil || p.FileID == uuid.Nil || p.Generation <= 0 || p.EmbeddingModel == "" || p.VectorDimension <= 0 {
			return nil, Dependency()
		}
	}
	return *response.Result.Points, nil
}

func postJSON(ctx context.Context, client *http.Client, endpoint, header, key string, body, target any) error {
	data, err := json.Marshal(body)
	if err != nil {
		return Dependency()
	}
	request, err := http.NewRequestWithContext(ctx, "POST", endpoint, bytes.NewReader(data))
	if err != nil {
		return Dependency()
	}
	request.Header.Set(header, key)
	request.Header.Set("Content-Type", "application/json")
	response, err := client.Do(request)
	if err != nil {
		return Dependency()
	}
	defer response.Body.Close()
	const max = 8 * 1048576
	if response.StatusCode < 200 || response.StatusCode > 299 || response.ContentLength > max {
		return Dependency()
	}
	data, err = io.ReadAll(io.LimitReader(response.Body, max+1))
	if err != nil || len(data) > max || json.Unmarshal(data, target) != nil {
		return Dependency()
	}
	return nil
}
