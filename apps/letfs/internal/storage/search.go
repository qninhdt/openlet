package storage

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"

	"github.com/google/uuid"
	"github.com/openai/openai-go/v3"
	"github.com/qdrant/go-client/qdrant"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/protobuf/encoding/protojson"
)

func literalPattern(query string) string {
	return "%" + strings.NewReplacer("\\", "\\\\", "%", "\\%", "_", "\\_").Replace(query) + "%"
}
func (s *Server) literalSearch(ctx context.Context, workspace, storage string, root *pb.NodeLocator, query, cursor string, size int, caseSensitive, text bool) ([]*pb.TextHit, string, error) {
	if _, err := s.check(ctx, "storage", storage, "read"); err != nil {
		return nil, "", err
	}
	if cursor != "" {
		if _, err := uuid.Parse(cursor); err != nil {
			return nil, "", invalid("invalid search cursor")
		}
	}
	input, err := locatorJSON([]*pb.NodeLocator{root})
	if err != nil {
		return nil, "", err
	}
	column := "n.name"
	if text {
		column = "f.text_content"
	}
	operator := "ILIKE"
	if caseSensitive {
		operator = "LIKE"
	}
	sql := resolverCTE + `,candidates AS MATERIALIZED(SELECT n.id FROM nodes n JOIN files f ON f.node_id=n.id WHERE n.storage_id=$2 AND ` + column + ` ` + operator + ` $4 AND ($5::uuid IS NULL OR n.id>$5) ORDER BY n.id LIMIT $6),
 ancestry AS(SELECT c.id AS candidate,n.id,n.parent_id,n.kind,0 AS depth FROM candidates c JOIN nodes n ON n.id=c.id UNION ALL SELECT a.candidate,n.id,n.parent_id,n.kind,a.depth+1 FROM ancestry a JOIN nodes n ON n.id=a.parent_id),
 eligible AS(SELECT a.candidate,bool_or(a.id=r.id) AS live,bool_or(a.depth>0 AND a.kind='file') AS readonly FROM ancestry a CROSS JOIN resolved r GROUP BY a.candidate)
 SELECT r.id,c.id,CASE WHEN e.live THEN ` + headerSQL + ` END,CASE WHEN e.live AND $7 THEN substring(f.text_content FROM greatest(1,strpos(lower(f.text_content),lower($8))-80) FOR 240) END FROM resolved r LEFT JOIN candidates c ON true LEFT JOIN eligible e ON e.candidate=c.id LEFT JOIN nodes n ON n.id=c.id CROSS JOIN LATERAL(SELECT coalesce(e.readonly,false) AS readonly) v ` + headerJoins + ` ORDER BY c.id`
	rows, err := s.DB.Query(ctx, sql, workspace, storage, input, literalPattern(query), nilString(cursor), size+1, text, query)
	if err != nil {
		return nil, "", err
	}
	defer rows.Close()
	hits := []*pb.TextHit{}
	ids := []string{}
	exists := false
	for rows.Next() {
		exists = true
		var rootID string
		var id *string
		var raw []byte
		var snippet *string
		if err = rows.Scan(&rootID, &id, &raw, &snippet); err != nil {
			return nil, "", err
		}
		if id == nil {
			continue
		}
		ids = append(ids, *id)
		if len(ids) > size {
			continue
		}
		if raw != nil {
			n := new(pb.Node)
			if err = protojson.Unmarshal(raw, n); err != nil {
				return nil, "", err
			}
			h := &pb.TextHit{Node: n}
			if snippet != nil {
				h.Snippet = *snippet
			}
			hits = append(hits, h)
		}
	}
	if err = rows.Err(); err != nil {
		return nil, "", err
	}
	if !exists {
		return nil, "", notFound()
	}
	next := ""
	if len(ids) > size {
		next = ids[size-1]
	}
	return hits, next, nil
}
func (s *Server) SearchFiles(ctx context.Context, r *pb.SearchFilesRequest) (*pb.SearchFilesResponse, error) {
	hits, next, err := s.literalSearch(ctx, r.WorkspaceId, r.StorageId, r.Root, r.Query, r.PageToken, pageSize(r.PageSize), r.CaseSensitive, false)
	if err != nil {
		return nil, err
	}
	out := &pb.SearchFilesResponse{NextPageToken: next}
	for _, hit := range hits {
		out.Hits = append(out.Hits, hit.Node)
	}
	return out, nil
}
func (s *Server) TextSearch(ctx context.Context, r *pb.TextSearchRequest) (*pb.TextSearchResponse, error) {
	if !r.LinesMode {
		hits, next, err := s.literalSearch(ctx, r.WorkspaceId, r.StorageId, r.Root, r.Query, r.PageToken, pageSize(r.PageSize), r.CaseSensitive, true)
		return &pb.TextSearchResponse{Hits: hits, NextPageToken: next}, err
	}
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	v, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Root, true, false)
	if err != nil {
		return nil, err
	}
	if v.Text == nil {
		return nil, invalid("lines mode requires a text file")
	}
	after := 0
	if r.PageToken != "" {
		after, err = strconv.Atoi(r.PageToken)
		if err != nil || after < 0 {
			return nil, invalid("invalid line cursor")
		}
	}
	needle := r.Query
	if !r.CaseSensitive {
		needle = strings.ToLower(needle)
	}
	out := new(pb.TextSearchResponse)
	for i, line := range textLines(*v.Text) {
		if i < after {
			continue
		}
		hay := line
		if !r.CaseSensitive {
			hay = strings.ToLower(hay)
		}
		if strings.Contains(hay, needle) {
			if len(out.Hits) == pageSize(r.PageSize) {
				out.NextPageToken = strconv.Itoa(int(out.Hits[len(out.Hits)-1].LineNumber))
				break
			}
			out.Hits = append(out.Hits, &pb.TextHit{Node: v.Node, Snippet: line, LineNumber: uint32(i + 1)})
		}
	}
	return out, nil
}
func (s *Server) SemanticSearch(ctx context.Context, r *pb.SemanticSearchRequest) (*pb.SemanticSearchResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	input, err := locatorJSON([]*pb.NodeLocator{r.Root})
	if err != nil {
		return nil, err
	}
	embeddings, err := s.Models.Embeddings.New(ctx, openai.EmbeddingNewParams{Model: openai.EmbeddingModel(s.EmbeddingModel), Dimensions: openai.Int(s.EmbeddingDimensions), Input: openai.EmbeddingNewParamsInputUnion{OfString: openai.String(r.Query)}})
	if err != nil {
		return nil, err
	}
	if len(embeddings.Data) != 1 {
		return nil, fmt.Errorf("embedding provider returned no query vector")
	}
	vector := make([]float32, len(embeddings.Data[0].Embedding))
	for i, v := range embeddings.Data[0].Embedding {
		vector[i] = float32(v)
	}
	limit := uint64(r.TopK) * 3
	filter := &qdrant.Filter{Must: []*qdrant.Condition{qdrant.NewMatchKeyword("workspace_id", r.WorkspaceId)}}
	textField := "text"
	points, err := s.Qdrant.Query(ctx, &qdrant.QueryPoints{
		CollectionName: s.Collection,
		Prefetch: []*qdrant.PrefetchQuery{
			{Query: qdrant.NewQuery(vector...), Filter: filter, Limit: &limit},
			{Query: qdrant.NewQueryText(qdrant.NewTextQueryBM25(r.Query, &qdrant.Bm25Params{})), Using: &textField, Filter: filter, Limit: &limit},
		},
		Query: qdrant.NewQueryFusion(qdrant.Fusion_RRF), Limit: &limit, WithPayload: qdrant.NewWithPayload(true),
	})
	if err != nil {
		return nil, err
	}
	records := []map[string]any{}
	for _, p := range points {
		file := p.Payload["file_id"].GetStringValue()
		source := p.Payload["source_id"].GetStringValue()
		version := p.Payload["source_version"].GetIntegerValue()
		if _, err = uuid.Parse(file); err != nil {
			continue
		}
		if _, err = uuid.Parse(source); err != nil {
			continue
		}
		records = append(records, map[string]any{"file": file, "source": source, "version": version, "score": p.Score, "snippet": p.Payload["text"].GetStringValue()})
	}
	raw, err := json.Marshal(records)
	if err != nil {
		return nil, err
	}
	rows, err := s.DB.Query(ctx, resolverCTE+`,candidates AS(SELECT x.* FROM jsonb_to_recordset($4::jsonb) x(file uuid,source uuid,version bigint,score float8,snippet text) JOIN files sf ON sf.node_id=x.source AND sf.version=x.version JOIN processing sp ON sp.file_id=sf.node_id AND sp.stage='ready'),
 ancestry AS(SELECT c.file,c.source,c.score,c.snippet,n.id,n.parent_id,n.kind,0 AS depth FROM candidates c JOIN nodes n ON n.id=c.file AND n.storage_id=$2 UNION ALL SELECT a.file,a.source,a.score,a.snippet,n.id,n.parent_id,n.kind,a.depth+1 FROM ancestry a JOIN nodes n ON n.id=a.parent_id),
 eligible AS(SELECT a.file,a.source,max(a.score) AS score,(array_agg(a.snippet ORDER BY a.score DESC))[1] AS snippet,bool_or(a.id=r.id) AND bool_or(a.id=a.source) AS live,bool_or(a.depth>0 AND a.kind='file') AS readonly FROM ancestry a CROSS JOIN resolved r GROUP BY a.file,a.source)
 SELECT `+headerSQL+`,e.snippet,e.score FROM eligible e JOIN nodes n ON n.id=e.file CROSS JOIN LATERAL(SELECT e.readonly) v `+headerJoins+` WHERE e.live ORDER BY e.score DESC LIMIT $5`, r.WorkspaceId, r.StorageId, input, raw, r.TopK*3)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := new(pb.SemanticSearchResponse)
	for rows.Next() {
		var nodeRaw []byte
		hit := new(pb.SemanticHit)
		if err = rows.Scan(&nodeRaw, &hit.Snippet, &hit.Score); err != nil {
			return nil, err
		}
		hit.Node = new(pb.Node)
		if err = protojson.Unmarshal(nodeRaw, hit.Node); err != nil {
			return nil, err
		}
		out.Hits = append(out.Hits, hit)
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	rows.Close()
	if len(out.Hits) == 0 {
		return out, nil
	}
	documents := make([]map[string]string, len(out.Hits))
	for i, h := range out.Hits {
		documents[i] = map[string]string{"text": h.Snippet}
	}
	var ranked struct {
		Results []struct {
			Index int     `json:"index"`
			Score float64 `json:"relevance_score"`
		} `json:"results"`
	}
	if err = s.Models.Post(ctx, "rerank", map[string]any{"model": s.RerankingModel, "query": r.Query, "documents": documents, "top_n": r.TopK}, &ranked); err != nil {
		return nil, err
	}
	result := new(pb.SemanticSearchResponse)
	for _, v := range ranked.Results {
		if v.Index < 0 || v.Index >= len(out.Hits) {
			return nil, fmt.Errorf("reranker returned an invalid document index")
		}
		hit := out.Hits[v.Index]
		hit.Score = v.Score
		result.Hits = append(result.Hits, hit)
	}
	return result, nil
}
