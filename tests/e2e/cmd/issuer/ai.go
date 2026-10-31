package main

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/json"
	"math"
	"net/http"
	"sort"
	"strings"
	"sync"
)

func aiRoutes(mux *http.ServeMux) {
	var mu sync.RWMutex
	failures := map[string]bool{}
	mux.HandleFunc("POST /ai-control", func(w http.ResponseWriter, r *http.Request) {
		var in map[string]bool
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 1024)).Decode(&in) != nil {
			w.WriteHeader(400)
			return
		}
		mu.Lock()
		failures = in
		mu.Unlock()
		w.WriteHeader(204)
	})
	mux.HandleFunc("POST /api/v1/{endpoint}", func(w http.ResponseWriter, r *http.Request) {
		endpoint := r.PathValue("endpoint")
		mu.RLock()
		fail := failures[endpoint]
		mu.RUnlock()
		if fail {
			w.WriteHeader(503)
			return
		}
		var in struct {
			Model      string          `json:"model"`
			Input      []string        `json:"input"`
			Dimensions int             `json:"dimensions"`
			Messages   json.RawMessage `json:"messages"`
			Documents  []string        `json:"documents"`
			Query      string          `json:"query"`
			TopN       int             `json:"top_n"`
		}
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 4*1048576)).Decode(&in) != nil || in.Model == "" {
			w.WriteHeader(400)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		write := func(v any) { _ = json.NewEncoder(w).Encode(v) }
		switch endpoint {
		case "chat":
			w.WriteHeader(404)
		case "embeddings":
			if in.Dimensions < 1 || in.Dimensions > 65536 || len(in.Input) == 0 {
				w.WriteHeader(400)
				return
			}
			data := []any{}
			for i, text := range in.Input {
				vector := make([]float64, in.Dimensions)
				for _, word := range strings.Fields(strings.ToLower(text)) {
					digest := sha256.Sum256([]byte(strings.Trim(word, ".,;:!?()[]{}\"")))
					vector[int(binary.LittleEndian.Uint32(digest[:4]))%in.Dimensions]++
				}
				norm := 0.0
				for _, v := range vector {
					norm += v * v
				}
				if norm == 0 {
					vector[0] = 1
				} else {
					for j := range vector {
						vector[j] /= math.Sqrt(norm)
					}
				}
				data = append(data, map[string]any{"object": "embedding", "index": i, "embedding": vector})
			}
			write(map[string]any{"object": "list", "model": in.Model, "data": data, "usage": map[string]int{"prompt_tokens": 1, "total_tokens": 1}})
		case "rerank":
			type result struct {
				Index int     `json:"index"`
				Score float64 `json:"relevance_score"`
			}
			results := []result{}
			for i, doc := range in.Documents {
				score := 0.0
				for _, word := range strings.Fields(strings.ToLower(in.Query)) {
					if strings.Contains(strings.ToLower(doc), word) {
						score++
					}
				}
				results = append(results, result{i, score})
			}
			sort.SliceStable(results, func(i, j int) bool { return results[i].Score > results[j].Score })
			if in.TopN > 0 && in.TopN < len(results) {
				results = results[:in.TopN]
			}
			write(map[string]any{"results": results})
		default:
			w.WriteHeader(404)
		}
	})
	mux.HandleFunc("POST /api/v1/chat/completions", func(w http.ResponseWriter, r *http.Request) {
		mu.RLock()
		fail := failures["generation"]
		mu.RUnlock()
		if fail {
			w.WriteHeader(503)
			return
		}
		var in struct {
			Model    string `json:"model"`
			Messages []struct {
				Role    string `json:"role"`
				Content any    `json:"content"`
			} `json:"messages"`
		}
		if json.NewDecoder(http.MaxBytesReader(w, r.Body, 4*1048576)).Decode(&in) != nil || in.Model == "" {
			w.WriteHeader(400)
			return
		}
		evidence := ""
		for _, message := range in.Messages {
			if message.Role == "user" {
				if parts, ok := message.Content.([]any); ok {
					for _, part := range parts {
						if p, ok := part.(map[string]any); ok && p["type"] == "text" {
							if v, ok := p["text"].(string); ok {
								evidence = v
							}
						}
					}
				}
			}
		}
		content := []rune(evidence)
		if len(content) > 2000 {
			content = content[:2000]
		}
		metadata, _ := json.Marshal(map[string]string{"title": "Untitled", "description": "File contains extracted document material.", "type": "unknown", "context": "Document material: " + string(content)})
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(map[string]any{"id": "test-generation", "object": "chat.completion", "created": 0, "model": in.Model, "choices": []any{map[string]any{"index": 0, "finish_reason": "stop", "message": map[string]any{"role": "assistant", "content": string(metadata)}}}, "usage": map[string]int{"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
	})
}
