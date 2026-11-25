package storage

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"path"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/option"
	"github.com/qdrant/go-client/qdrant"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/baggage"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/trace"
	"google.golang.org/grpc/metadata"
)

func likeOp(caseSensitive bool) string {
	if caseSensitive {
		return "LIKE"
	}
	return "ILIKE"
}

func snippetExpr(col, needleArg string, caseSensitive bool) string {
	if caseSensitive {
		return fmt.Sprintf(`substring(%s FROM greatest(1,strpos(%s,%s)-80) FOR 240)`, col, col, needleArg)
	}
	return fmt.Sprintf(`substring(%s FROM greatest(1,strpos(lower(%s),lower(%s))-80) FOR 240)`, col, col, needleArg)
}

func (s *Server) SearchFiles(ctx context.Context, r *pb.SearchFilesRequest) (*pb.SearchFilesResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	root, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Root, false, false)
	if err != nil {
		return nil, err
	}
	if root.Artifact != nil {
		return &pb.SearchFilesResponse{}, nil
	}
	limit := pageSize(r.PageSize)
	rows, err := s.DB.Query(ctx, `WITH RECURSIVE tree AS (
		SELECT n.id,n.kind FROM nodes n WHERE n.id=$1 AND n.storage_id=$2
		UNION ALL
		SELECT c.id,c.kind FROM tree t JOIN nodes c ON c.parent_id=t.id AND c.storage_id=$2 WHERE t.kind='directory'
	)
	SELECT `+nodeColumns+`
	FROM tree t JOIN nodes n ON n.id=t.id `+nodeJoins+`
	WHERE n.name `+likeOp(r.CaseSensitive)+` $3 ESCAPE '\' AND ($4::uuid IS NULL OR n.id>$4)
	ORDER BY n.id LIMIT $5`,
		root.Node.Id, r.StorageId, literalPattern(r.Query), nilString(r.PageToken), limit+1)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := new(pb.SearchFilesResponse)
	for rows.Next() {
		var sc nodeScanner
		if err = rows.Scan(sc.dests()...); err != nil {
			return nil, err
		}
		out.Hits = append(out.Hits, sc.finish(false))
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	if len(out.Hits) > limit {
		out.Hits = out.Hits[:limit]
		out.NextPageToken = out.Hits[limit-1].Id
	}
	return out, nil
}

func (s *Server) TextSearch(ctx context.Context, r *pb.TextSearchRequest) (*pb.TextSearchResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	root, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Root, true, false)
	if err != nil {
		return nil, err
	}
	if r.LinesMode {
		return textSearchLines(root, r)
	}

	afterPath, err := decodeTextCursor(r.PageToken)
	if err != nil {
		return nil, err
	}
	pattern := literalPattern(r.Query)
	op := likeOp(r.CaseSensitive)
	limit := pageSize(r.PageSize)

	if root.Artifact != nil {
		return s.textSearchArtifactRoot(ctx, r, root, pattern, op, afterPath, limit)
	}
	if root.Node.Kind == pb.NodeKind_NODE_KIND_FILE {
		return s.textSearchFileRoot(ctx, r, root, pattern, op, afterPath, limit)
	}

	// Directory root: sort/limit lightweight key rows first, then fetch payloads & snippets only for winning rows.
	rows, err := s.DB.Query(ctx, `WITH RECURSIVE tree AS (
		SELECT n.id,n.kind,''::text AS rel_path
		FROM nodes n WHERE n.id=$1 AND n.storage_id=$2
		UNION ALL
		SELECT c.id,c.kind,CASE WHEN t.rel_path='' THEN c.name ELSE t.rel_path||'/'||c.name END
		FROM tree t JOIN nodes c ON c.parent_id=t.id AND c.storage_id=$2
		WHERE t.kind='directory'
	),
	tree_files AS MATERIALIZED (
		SELECT t.rel_path,f.node_id,f.blob_id,f.text_content IS NOT NULL AS has_text
		FROM tree t JOIN files f ON f.node_id=t.id
	),
	matches AS (
		SELECT tf.rel_path AS hit_path,''::text AS art_path,tf.node_id AS row_id,tf.node_id AS base_file_id
		FROM tree_files tf
		JOIN files f ON f.node_id=tf.node_id
		WHERE tf.has_text AND f.text_content `+op+` $3 ESCAPE '\'
		UNION ALL
		SELECT CASE WHEN tf.rel_path='' THEN a.path ELSE tf.rel_path||'/'||a.path END AS hit_path,a.path AS art_path,a.id AS row_id,tf.node_id AS base_file_id
		FROM tree_files tf
		JOIN blob_artifacts a ON a.blob_id=tf.blob_id
		WHERE a.text_content IS NOT NULL AND a.text_content `+op+` $3 ESCAPE '\'
	),
	page AS (
		SELECT hit_path,art_path,row_id,base_file_id
		FROM matches WHERE ($5::text='' OR hit_path>$5) ORDER BY hit_path LIMIT $6
	)
	SELECT p.hit_path,p.art_path,p.row_id::text,coalesce(pa.id,p.base_file_id)::text,
	       coalesce(a.media_type,''),coalesce(a.size_bytes,0),coalesce(a.title,''),coalesce(a.description,''),coalesce(a.created_at,'epoch'::timestamptz),
	       `+snippetExpr("coalesce(a.text_content,f.text_content)", "$4", r.CaseSensitive)+`,
	       coalesce(n.id::text,''),coalesce(n.storage_id::text,''),n.parent_id::text,coalesce(n.name,''),coalesce(n.kind::text,''),coalesce(n.created_at,'epoch'::timestamptz),coalesce(n.updated_at,'epoch'::timestamptz),
	       coalesce(f.node_id IS NOT NULL,false),f.version,f.size_bytes,f.media_type,f.blob_id::text,f.text_content IS NOT NULL,
	       coalesce(b.title,''),coalesce(b.description,''),b.processing_stage,coalesce(b.processing_error_code,'')
	FROM page p
	LEFT JOIN nodes n ON p.art_path='' AND n.id=p.row_id
	LEFT JOIN files f ON p.art_path='' AND f.node_id=p.row_id
	LEFT JOIN blobs b ON p.art_path='' AND b.id=f.blob_id
	LEFT JOIN blob_artifacts a ON p.art_path<>'' AND a.id=p.row_id
	LEFT JOIN blob_artifacts pa ON p.art_path<>'' AND pa.blob_id=a.blob_id AND pa.path=a.parent_path AND a.parent_path<>''
	ORDER BY p.hit_path`,
		root.Node.Id, r.StorageId, pattern, r.Query, afterPath, limit+1)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := new(pb.TextSearchResponse)
	for rows.Next() {
		var hitPath, artPath, rowID, artParentID, artMedia, artTitle, artDesc, snippet string
		var artSize int64
		var artCreated time.Time
		var sc nodeScanner
		if err = rows.Scan(
			&hitPath, &artPath, &rowID, &artParentID, &artMedia, &artSize, &artTitle, &artDesc, &artCreated, &snippet,
			&sc.node.Id, &sc.node.StorageId, &sc.parentID, &sc.node.Name, &sc.kind, &sc.created, &sc.updated,
			&sc.hasFile, &sc.version, &sc.sizeBytes, &sc.mediaType, &sc.blobID, &sc.hasText,
			&sc.title, &sc.desc, &sc.stage, &sc.errCode,
		); err != nil {
			return nil, err
		}
		var node *pb.Node
		if artPath == "" {
			node = sc.finish(false)
		} else {
			empty := ""
			node = buildArtifactNode(r.StorageId, artParentID, blobArtifact{
				ID: rowID, Path: artPath, Kind: "file", MediaType: artMedia, SizeBytes: artSize, TextContent: &empty,
			}, artTitle, artDesc, artCreated)
		}
		out.Hits = append(out.Hits, &pb.TextHit{Node: node, Snippet: snippet, Path: hitPath, ArtifactPath: artPath})
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	if len(out.Hits) > limit {
		out.Hits = out.Hits[:limit]
		out.NextPageToken = encodeTextCursor(out.Hits[limit-1].Path)
	}
	return out, nil
}

func derefStr(v *string) string {
	if v == nil {
		return ""
	}
	return *v
}

func textSearchLines(root resolved, r *pb.TextSearchRequest) (*pb.TextSearchResponse, error) {
	if root.Text == nil {
		return nil, invalid("lines mode requires a text file")
	}
	startLine := 0
	if r.PageToken != "" {
		raw, err := decodeTextCursor(r.PageToken)
		if err != nil {
			return nil, err
		}
		n, err := strconv.Atoi(raw)
		if err != nil || n < 0 {
			return nil, invalid("invalid cursor")
		}
		startLine = n
	}
	limit := pageSize(r.PageSize)
	artPath := ""
	if root.Artifact != nil {
		artPath = root.Artifact.Path
	}
	needle := r.Query
	if !r.CaseSensitive {
		needle = strings.ToLower(needle)
	}
	out := new(pb.TextSearchResponse)
	for i, line := range textLines(*root.Text) {
		lineNum := i + 1
		if lineNum <= startLine {
			continue
		}
		haystack := line
		if !r.CaseSensitive {
			haystack = strings.ToLower(haystack)
		}
		if strings.Contains(haystack, needle) {
			if len(out.Hits) >= limit {
				out.NextPageToken = encodeTextCursor(strconv.Itoa(int(out.Hits[limit-1].LineNumber)))
				break
			}
			out.Hits = append(out.Hits, &pb.TextHit{
				Node: root.Node, Snippet: line, LineNumber: uint32(lineNum), Path: ".", ArtifactPath: artPath,
			})
		}
	}
	return out, nil
}

func (s *Server) textSearchArtifactRoot(ctx context.Context, r *pb.TextSearchRequest, root resolved, pattern, op, afterPath string, limit int) (*pb.TextSearchResponse, error) {
	if root.Artifact.Kind == "file" {
		if root.Text == nil {
			return &pb.TextSearchResponse{}, nil
		}
		matched, idx := matchSubstring(*root.Text, r.Query, r.CaseSensitive)
		if !matched || (afterPath != "" && "." <= afterPath) {
			return &pb.TextSearchResponse{}, nil
		}
		start := max(0, idx-80)
		end := min(len(*root.Text), start+240)
		return &pb.TextSearchResponse{Hits: []*pb.TextHit{{
			Node: root.Node, Snippet: (*root.Text)[start:end], Path: ".", ArtifactPath: root.Artifact.Path,
		}}}, nil
	}
	rows, err := s.DB.Query(ctx, `SELECT `+artifactColumns+`,`+artifactPayloadCols(false)+`,`+snippetExpr("a.text_content", "$4", r.CaseSensitive)+`
		FROM blob_artifacts a
		WHERE a.blob_id=$1 AND a.path LIKE $2 ESCAPE '\' AND a.text_content IS NOT NULL
		  AND a.text_content `+op+` $3 ESCAPE '\'
		  AND ($5::text='' OR trim(leading $6 from a.path)>$5)
		ORDER BY a.path LIMIT $7`,
		root.Artifact.BlobID, prefixPattern(root.Artifact.Path), pattern, r.Query, afterPath, root.Artifact.Path+"/", limit+1)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := new(pb.TextSearchResponse)
	for rows.Next() {
		var sc artifactScanner
		var snippet string
		if err = rows.Scan(sc.dests(false, &snippet)...); err != nil {
			return nil, err
		}
		rel := strings.TrimPrefix(sc.a.Path, root.Artifact.Path+"/")
		out.Hits = append(out.Hits, &pb.TextHit{
			Node: sc.build(r.StorageId, root.Node.Id, false), Snippet: snippet, Path: rel, ArtifactPath: sc.a.Path,
		})
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	if len(out.Hits) > limit {
		out.Hits = out.Hits[:limit]
		out.NextPageToken = encodeTextCursor(out.Hits[limit-1].Path)
	}
	return out, nil
}

func (s *Server) textSearchFileRoot(ctx context.Context, r *pb.TextSearchRequest, root resolved, pattern, op, afterPath string, limit int) (*pb.TextSearchResponse, error) {
	if root.BlobID == nil {
		if root.Text == nil {
			return &pb.TextSearchResponse{}, nil
		}
		matched, idx := matchSubstring(*root.Text, r.Query, r.CaseSensitive)
		if !matched || (afterPath != "" && "." <= afterPath) {
			return &pb.TextSearchResponse{}, nil
		}
		start := max(0, idx-80)
		end := min(len(*root.Text), start+240)
		return &pb.TextSearchResponse{Hits: []*pb.TextHit{{
			Node: root.Node, Snippet: (*root.Text)[start:end], Path: ".",
		}}}, nil
	}
	rows, err := s.DB.Query(ctx, `SELECT `+artifactColumns+`,`+artifactPayloadCols(false)+`,coalesce(pa.id,$1),`+snippetExpr("a.text_content", "$4", r.CaseSensitive)+`
		FROM blob_artifacts a LEFT JOIN blob_artifacts pa ON pa.blob_id=a.blob_id AND pa.path=a.parent_path AND a.parent_path<>''
		WHERE a.blob_id=$2 AND a.text_content IS NOT NULL AND a.text_content `+op+` $3 ESCAPE '\'
		  AND ($5::text='' OR a.path>$5)
		ORDER BY a.path LIMIT $6`,
		root.Node.Id, *root.BlobID, pattern, r.Query, afterPath, limit+1)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := new(pb.TextSearchResponse)
	for rows.Next() {
		var sc artifactScanner
		var parentID, snippet string
		if err = rows.Scan(sc.dests(false, &parentID, &snippet)...); err != nil {
			return nil, err
		}
		out.Hits = append(out.Hits, &pb.TextHit{
			Node: sc.build(r.StorageId, parentID, false), Snippet: snippet, Path: sc.a.Path, ArtifactPath: sc.a.Path,
		})
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	if len(out.Hits) > limit {
		out.Hits = out.Hits[:limit]
		out.NextPageToken = encodeTextCursor(out.Hits[limit-1].Path)
	}
	return out, nil
}

func matchSubstring(haystack, needle string, caseSensitive bool) (bool, int) {
	if caseSensitive {
		idx := strings.Index(haystack, needle)
		return idx >= 0, idx
	}
	idx := strings.Index(strings.ToLower(haystack), strings.ToLower(needle))
	return idx >= 0, idx
}

func encodeTextCursor(path string) string {
	return base64.RawURLEncoding.EncodeToString([]byte(path))
}

func decodeTextCursor(token string) (string, error) {
	if token == "" {
		return "", nil
	}
	raw, err := base64.RawURLEncoding.DecodeString(token)
	if err != nil {
		return "", invalid("invalid cursor")
	}
	return string(raw), nil
}

const storagePathSQL = `WITH RECURSIVE chain AS (
 SELECT n.id, n.parent_id, '/' || n.name AS path FROM nodes n WHERE n.id=$3 AND n.storage_id=$2
 UNION ALL
 SELECT n.id, n.parent_id, CASE WHEN n.name='' THEN c.path ELSE '/' || n.name || c.path END
 FROM chain c JOIN nodes n ON n.id=c.parent_id AND n.storage_id=$2
)
SELECT c.path FROM chain c JOIN storages s ON s.root_node_id=c.id WHERE s.id=$2 AND s.workspace_id=$1`

func storagePath(ctx context.Context, db queryer, workspace, storage, node string) (string, error) {
	var p string
	err := db.QueryRow(ctx, storagePathSQL, workspace, storage, node).Scan(&p)
	if err == pgx.ErrNoRows {
		return "", notFound()
	}
	return p, err
}

func (s *Server) queryQdrantHybrid(ctx context.Context, workspaceID string, blobIDs []string, vector []float32, query string, prefetchLimit, limit uint64) ([]*qdrant.ScoredPoint, error) {
	const batchCap = 2000
	textField := "text"
	buildQuery := func(ids []string) *qdrant.QueryPoints {
		filter := &qdrant.Filter{Must: []*qdrant.Condition{
			qdrant.NewMatchKeyword("workspace_id", workspaceID),
			qdrant.NewMatchKeywords("blob_id", ids...),
		}}
		return &qdrant.QueryPoints{
			CollectionName: s.Collection,
			Prefetch: []*qdrant.PrefetchQuery{
				{Query: qdrant.NewQuery(vector...), Filter: filter, Limit: &prefetchLimit},
				{Query: qdrant.NewQueryText(qdrant.NewTextQueryBM25(query, &qdrant.Bm25Params{})), Using: &textField, Filter: filter, Limit: &prefetchLimit},
			},
			Query:           qdrant.NewQueryFusion(qdrant.Fusion_RRF),
			Limit:           &limit,
			WithPayload:     qdrant.NewWithPayloadInclude("blob_id", "artifact_path", "text"),
			ReadConsistency: qdrant.NewReadConsistencyType(qdrant.ReadConsistencyType_All),
		}
	}
	if len(blobIDs) <= batchCap {
		return s.Qdrant.Query(ctx, buildQuery(blobIDs))
	}
	var batch []*qdrant.QueryPoints
	for start := 0; start < len(blobIDs); start += batchCap {
		end := min(len(blobIDs), start+batchCap)
		batch = append(batch, buildQuery(blobIDs[start:end]))
	}
	results, err := s.Qdrant.QueryBatch(ctx, &qdrant.QueryBatchPoints{
		CollectionName:  s.Collection,
		QueryPoints:     batch,
		ReadConsistency: qdrant.NewReadConsistencyType(qdrant.ReadConsistencyType_All),
	})
	if err != nil {
		return nil, err
	}
	var merged []*qdrant.ScoredPoint
	for _, res := range results {
		merged = append(merged, res.GetResult()...)
	}
	sort.Slice(merged, func(i, j int) bool { return merged[i].Score > merged[j].Score })
	if uint64(len(merged)) > limit {
		merged = merged[:limit]
	}
	return merged, nil
}

func (s *Server) SemanticSearch(ctx context.Context, r *pb.SemanticSearchRequest) (result *pb.SemanticSearchResponse, err error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	var target *pb.NodeLocator
	if p := r.Root.GetPath(); p != "" {
		if !strings.HasPrefix(p, "/") || strings.ContainsRune(p, 0) || path.Clean(p) != p {
			return nil, invalid("semantic search requires a canonical storage path")
		}
		target = &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: p}}
	} else {
		target = &pb.NodeLocator{Locator: &pb.NodeLocator_NodeId{NodeId: r.Root.GetNodeId()}}
	}
	rootRes, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, target, false, false)
	if err != nil {
		return nil, err
	}
	if !rootRes.AllowIndex || s.Qdrant == nil {
		return &pb.SemanticSearchResponse{}, nil
	}

	type liveRef struct {
		fileID string
		path   string
	}
	byBlob := map[string][]liveRef{}
	blobIDs := []string{}
	artFilter := ""

	if rootRes.Artifact != nil {
		parentFileID := rootRes.Chain[len(rootRes.Chain)-1]
		livePath, err := storagePath(ctx, s.DB, r.WorkspaceId, r.StorageId, parentFileID)
		if err != nil {
			return nil, err
		}
		var ready bool
		err = s.DB.QueryRow(ctx, `SELECT processing_stage='ready' AND delete_requested_at IS NULL FROM blobs WHERE id=$1`, rootRes.Artifact.BlobID).Scan(&ready)
		if err != nil || !ready {
			return &pb.SemanticSearchResponse{}, nil
		}
		byBlob[rootRes.Artifact.BlobID] = []liveRef{{fileID: parentFileID, path: livePath}}
		blobIDs = append(blobIDs, rootRes.Artifact.BlobID)
		artFilter = rootRes.Artifact.Path
	} else {
		basePath, err := storagePath(ctx, s.DB, r.WorkspaceId, r.StorageId, rootRes.Node.Id)
		if err != nil {
			return nil, err
		}
		rows, err := s.DB.Query(ctx, `WITH RECURSIVE tree AS (
			SELECT n.id,n.kind,$3::text AS path
			FROM nodes n WHERE n.id=$2 AND n.storage_id=$1
			UNION ALL
			SELECT c.id,c.kind,CASE WHEN t.path='/' THEN '/'||c.name ELSE t.path||'/'||c.name END
			FROM tree t JOIN nodes c ON c.parent_id=t.id AND c.storage_id=$1
			WHERE t.kind='directory'
		)
		SELECT t.id::text,t.path,f.blob_id::text
		FROM tree t
		JOIN files f ON f.node_id=t.id
		JOIN blobs b ON b.id=f.blob_id
		WHERE b.processing_stage='ready' AND b.delete_requested_at IS NULL
		ORDER BY t.path,t.id`, r.StorageId, rootRes.Node.Id, basePath)
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var fileID, livePath, blobID string
			if err = rows.Scan(&fileID, &livePath, &blobID); err != nil {
				rows.Close()
				return nil, err
			}
			if _, seen := byBlob[blobID]; !seen {
				blobIDs = append(blobIDs, blobID)
			}
			byBlob[blobID] = append(byBlob[blobID], liveRef{fileID: fileID, path: livePath})
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return nil, err
		}
	}
	if len(blobIDs) == 0 {
		return &pb.SemanticSearchResponse{}, nil
	}

	incoming, _ := metadata.FromIncomingContext(ctx)
	ctx = propagation.Baggage{}.Extract(ctx, propagation.MapCarrier{"baggage": strings.Join(incoming.Get("baggage"), ",")})
	span := trace.SpanFromContext(ctx)
	settings := s.Settings.SemanticSearch
	span.SetAttributes(ragAttributes(ctx)...)
	span.SetAttributes(
		attribute.String("langfuse.observation.type", "retriever"),
		attribute.String("langfuse.observation.input", r.Query),
		attribute.String("langfuse.observation.metadata.storage_id", r.StorageId),
		attribute.Int("langfuse.observation.metadata.result_limit", int(settings.ResultLimit)),
	)
	defer func() {
		if result == nil {
			return
		}
		body, _ := json.Marshal(result.Hits)
		span.SetAttributes(attribute.String("langfuse.observation.output", string(body)), attribute.Int("langfuse.observation.metadata.returned_count", len(result.Hits)))
	}()

	vector, err := s.queryEmbedding(ctx, r.Query)
	if err != nil {
		return nil, err
	}
	prefetchLimit := settings.CandidateLimit
	limit := settings.ResultLimit
	if s.RerankingModel != "" {
		limit = prefetchLimit
	}
	points, err := s.queryQdrantHybrid(ctx, r.WorkspaceId, blobIDs, vector, r.Query, prefetchLimit, limit)
	if err != nil {
		return nil, err
	}

	type chunkKey struct {
		blobID  string
		artPath string
		text    string
	}
	type scoredChunk struct {
		blobID  string
		artPath string
		text    string
		score   float64
	}
	seen := make(map[chunkKey]struct{}, len(points))
	var candidates []scoredChunk
	for _, point := range points {
		blobID := point.Payload["blob_id"].GetStringValue()
		if len(byBlob[blobID]) == 0 {
			continue
		}
		artPath := point.Payload["artifact_path"].GetStringValue()
		if artFilter != "" && artPath != artFilter && !strings.HasPrefix(artPath, artFilter+"/") {
			continue
		}
		text := point.Payload["text"].GetStringValue()
		key := chunkKey{blobID: blobID, artPath: artPath, text: text}
		if _, dup := seen[key]; dup {
			continue
		}
		seen[key] = struct{}{}
		candidates = append(candidates, scoredChunk{
			blobID: blobID, artPath: artPath, text: text, score: float64(point.Score),
		})
	}
	if s.RerankingModel != "" && len(candidates) > 0 {
		documents := make([]map[string]string, len(candidates))
		for i, c := range candidates {
			documents[i] = map[string]string{"text": c.text}
		}
		ranked, err := s.rerank(ctx, r.Query, documents, int(settings.ResultLimit))
		if err != nil {
			return nil, err
		}
		reordered := make([]scoredChunk, 0, len(ranked))
		for _, v := range ranked {
			c := candidates[v.Index]
			c.score = v.Score
			reordered = append(reordered, c)
		}
		candidates = reordered
	}

	result = new(pb.SemanticSearchResponse)
	for _, c := range candidates {
		for _, ref := range byBlob[c.blobID] {
			result.Hits = append(result.Hits, &pb.SemanticHit{
				FileId:       ref.fileID,
				Path:         ref.path,
				ArtifactPath: c.artPath,
				Text:         c.text,
				Score:        c.score,
			})
			if uint64(len(result.Hits)) >= settings.ResultLimit {
				return result, nil
			}
		}
	}
	return result, nil
}

func (s *Server) queryEmbedding(ctx context.Context, query string) ([]float32, error) {
	ctx, span := otel.Tracer("openlet.letfs").Start(ctx, "query_embedding")
	defer span.End()
	span.SetAttributes(ragAttributes(ctx)...)
	span.SetAttributes(
		attribute.String("langfuse.observation.type", "embedding"),
		attribute.String("langfuse.observation.input", query),
		attribute.String("gen_ai.operation.name", "embeddings"),
		attribute.String("gen_ai.request.model", s.EmbeddingModel),
	)
	var response *http.Response
	embeddings, err := s.Models.Embeddings.New(ctx, openai.EmbeddingNewParams{
		Model:          openai.EmbeddingModel(s.EmbeddingModel),
		Dimensions:     openai.Int(s.EmbeddingDimensions),
		EncodingFormat: openai.EmbeddingNewParamsEncodingFormatFloat,
		Input:          openai.EmbeddingNewParamsInputUnion{OfString: openai.String(query)},
	}, option.WithResponseInto(&response))
	if err != nil {
		span.SetStatus(codes.Error, "embedding failed")
		return nil, err
	}
	annotateCost(span, response)
	if len(embeddings.Data) != 1 || embeddings.Data[0].Index != 0 || len(embeddings.Data[0].Embedding) != int(s.EmbeddingDimensions) {
		span.SetStatus(codes.Error, "invalid embedding response")
		return nil, fmt.Errorf("embedding provider returned no query vector")
	}
	if embeddings.JSON.Usage.Valid() {
		span.SetAttributes(attribute.Int64("gen_ai.usage.input_tokens", embeddings.Usage.PromptTokens))
	}
	vector := make([]float32, len(embeddings.Data[0].Embedding))
	for i, v := range embeddings.Data[0].Embedding {
		vector[i] = float32(v)
	}
	span.SetAttributes(
		attribute.Int("langfuse.observation.metadata.dimensions", len(vector)),
		attribute.String("langfuse.observation.output", fmt.Sprintf(`{"count":1,"dimensions":%d}`, len(vector))),
	)
	return vector, nil
}

type rankedDocument struct {
	Index int     `json:"index"`
	Score float64 `json:"relevance_score"`
}

func (s *Server) rerank(ctx context.Context, query string, documents []map[string]string, topK int) ([]rankedDocument, error) {
	ctx, span := otel.Tracer("openlet.letfs").Start(ctx, "rerank")
	defer span.End()
	span.SetAttributes(ragAttributes(ctx)...)
	span.SetAttributes(
		attribute.String("langfuse.observation.type", "span"),
		attribute.String("langfuse.observation.input", query),
		attribute.String("langfuse.observation.metadata.model", s.RerankingModel),
		attribute.Int("langfuse.observation.metadata.candidate_count", len(documents)),
	)
	var ranked struct {
		Results []rankedDocument `json:"results"`
	}
	var response *http.Response
	if err := s.Models.Post(ctx, "rerank", map[string]any{
		"model": s.RerankingModel, "query": query, "documents": documents, "top_n": topK,
	}, &ranked, option.WithResponseInto(&response)); err != nil {
		span.SetStatus(codes.Error, "rerank failed")
		return nil, err
	}
	annotateCost(span, response)
	for _, v := range ranked.Results {
		if v.Index < 0 || v.Index >= len(documents) {
			span.SetStatus(codes.Error, "invalid rerank response")
			return nil, fmt.Errorf("reranker returned an invalid document index")
		}
	}
	return ranked.Results, nil
}

func annotateCost(span trace.Span, response *http.Response) {
	if response == nil {
		return
	}
	cost, err := strconv.ParseFloat(response.Header.Get("x-litellm-response-cost"), 64)
	if err == nil && !math.IsNaN(cost) && !math.IsInf(cost, 0) && cost >= 0 {
		body, _ := json.Marshal(map[string]float64{"total": cost})
		span.SetAttributes(attribute.String("langfuse.observation.cost_details", string(body)))
	}
}

// These labels describe attribution only; storage authorization uses the actor.
func ragAttributes(ctx context.Context) []attribute.KeyValue {
	b := baggage.FromContext(ctx)
	var attrs []attribute.KeyValue
	if id := b.Member("langfuse_session_id").Value(); uuid.Validate(id) == nil {
		attrs = append(attrs, attribute.String("session.id", id))
	}
	for _, key := range []string{"workspace_id", "agent_id", "leta_id", "box_id", "run_id"} {
		var id string
		if json.Unmarshal([]byte(b.Member("langfuse_metadata_"+key).Value()), &id) == nil && uuid.Validate(id) == nil {
			attrs = append(attrs, attribute.String("langfuse.observation.metadata."+key, id))
		}
	}
	return attrs
}
