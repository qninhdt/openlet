package storage

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net/http"
	"path"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/bmatcuk/doublestar/v4"
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
	"google.golang.org/protobuf/types/known/timestamppb"
)

func (s *Server) searchDefaultLimit() int {
	if s.Settings.Search.DefaultLimit > 0 {
		return s.Settings.Search.DefaultLimit
	}
	return 100
}

func (s *Server) searchMaxLimit() int {
	if s.Settings.Search.MaxLimit > 0 {
		return s.Settings.Search.MaxLimit
	}
	return 100
}

func (s *Server) searchTimeout() time.Duration {
	if s.Settings.Search.TimeoutSeconds > 0 {
		return time.Duration(s.Settings.Search.TimeoutSeconds) * time.Second
	}
	return 30 * time.Second
}

func (s *Server) searchMaxLineChars() int {
	if s.Settings.Search.MaxLineChars > 0 {
		return s.Settings.Search.MaxLineChars
	}
	return 2000
}

func (s *Server) semanticMaxResultLimit() uint64 {
	if s.Settings.SemanticSearch.MaxResultLimit > 0 {
		return s.Settings.SemanticSearch.MaxResultLimit
	}
	if s.Settings.SemanticSearch.ResultLimit > 25 {
		return s.Settings.SemanticSearch.ResultLimit
	}
	return 25
}

func (s *Server) semanticTimeout() time.Duration {
	if s.Settings.SemanticSearch.TimeoutSeconds > 0 {
		return time.Duration(s.Settings.SemanticSearch.TimeoutSeconds) * time.Second
	}
	return 30 * time.Second
}

func (s *Server) semanticMaxExcerptChars() int {
	if s.Settings.SemanticSearch.MaxExcerptChars > 0 {
		return s.Settings.SemanticSearch.MaxExcerptChars
	}
	return 2000
}

func (s *Server) effectiveSearchLimit(requested int32) int {
	limit := int(requested)
	if limit <= 0 {
		limit = s.searchDefaultLimit()
	}
	if maxLimit := s.searchMaxLimit(); limit > maxLimit {
		limit = maxLimit
	}
	return limit
}

func hasHiddenSegment(relPath string) bool {
	for _, seg := range strings.Split(relPath, "/") {
		if len(seg) > 1 && seg[0] == '.' {
			return true
		}
	}
	return false
}

func normalizeGlobPattern(pattern string) string {
	p := strings.TrimSpace(pattern)
	p = strings.TrimPrefix(p, "/")
	p = strings.TrimPrefix(p, "./")
	return p
}

func matchesIncludeGlob(glob, relPath string) bool {
	if glob == "" {
		return true
	}
	if ok, _ := doublestar.Match(glob, relPath); ok {
		return true
	}
	if !strings.Contains(glob, "/") {
		if ok, _ := doublestar.Match(glob, path.Base(relPath)); ok {
			return true
		}
	}
	return false
}

func clipRunes(s string, maxChars int) string {
	if maxChars <= 0 || len(s) <= maxChars {
		return s
	}
	count := 0
	for idx := range s {
		if count == maxChars {
			return s[:idx]
		}
		count++
	}
	return s
}

func likeOp(caseSensitive bool) string {
	if caseSensitive {
		return "LIKE"
	}
	return "ILIKE"
}

func regexOp(caseSensitive bool) string {
	if caseSensitive {
		return "~"
	}
	return "~*"
}

// pgSafeRegex converts common RE2 patterns into Postgres POSIX ERE for pg_trgm GIN pre-filtering.
// Returns ("", false) when the pattern uses line anchors or Go/RE2 constructs that differ in
// Postgres (whole-text ^/$, PCRE flags, or RE2 shorthand escapes like \d/\w/\s/\b), allowing
// the query to safely pre-filter by tree/glob and perform exact Go regex matching line-by-line.
func pgSafeRegex(pattern string) (string, bool) {
	if strings.Contains(pattern, "(?") || strings.Contains(pattern, "[:") || strings.ContainsAny(pattern, "^$") {
		return "", false
	}
	for i := 0; i < len(pattern); i++ {
		if pattern[i] != '\\' {
			continue
		}
		if i+1 >= len(pattern) {
			return "", false
		}
		next := pattern[i+1]
		if (next >= 'a' && next <= 'z') || (next >= 'A' && next <= 'Z') || (next >= '0' && next <= '9') {
			return "", false
		}
		i++
	}
	return pattern, true
}

func (s *Server) Glob(ctx context.Context, r *pb.GlobRequest) (*pb.GlobResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	pattern := normalizeGlobPattern(r.Pattern)
	if pattern == "" || !doublestar.ValidatePattern(pattern) {
		return nil, invalid("invalid glob pattern")
	}
	ctx, cancel := context.WithTimeout(ctx, s.searchTimeout())
	defer cancel()

	root, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Root, false, false)
	if err != nil {
		return nil, err
	}
	limit := s.effectiveSearchLimit(r.Limit)
	out := new(pb.GlobResponse)

	matchAndAppend := func(hit *pb.GlobHit) bool {
		if !r.IncludeHidden && hasHiddenSegment(hit.Path) {
			return false
		}
		matched, _ := doublestar.Match(pattern, hit.Path)
		if !matched {
			return false
		}
		if len(out.Hits) >= limit {
			out.Truncated = true
			return true
		}
		out.Hits = append(out.Hits, hit)
		return false
	}

	if root.Artifact != nil {
		if root.Artifact.Kind == "file" {
			name := path.Base(root.Artifact.Path)
			matchAndAppend(&pb.GlobHit{
				Path:         name,
				NodeId:       root.Node.Id,
				Kind:         root.Node.Kind,
				ArtifactPath: root.Artifact.Path,
				SizeBytes:    root.Artifact.SizeBytes,
				UpdatedAt:    root.Node.UpdatedAt,
			})
			return out, nil
		}
		rows, err := s.DB.Query(ctx, `SELECT a.id::text,a.path,a.kind,a.size_bytes,a.created_at
			FROM blob_artifacts a
			WHERE a.blob_id=$1 AND a.path LIKE $2 ESCAPE '\'
			ORDER BY a.path`,
			root.Artifact.BlobID, prefixPattern(root.Artifact.Path))
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		prefix := root.Artifact.Path + "/"
		for rows.Next() {
			var id, artPath, kind string
			var size int64
			var created time.Time
			if err = rows.Scan(&id, &artPath, &kind, &size, &created); err != nil {
				return nil, err
			}
			rel := strings.TrimPrefix(artPath, prefix)
			nk := pb.NodeKind_NODE_KIND_DIRECTORY
			if kind == "file" {
				nk = pb.NodeKind_NODE_KIND_FILE
			}
			if matchAndAppend(&pb.GlobHit{
				Path:         rel,
				NodeId:       id,
				Kind:         nk,
				ArtifactPath: artPath,
				SizeBytes:    size,
				UpdatedAt:    timestamppb.New(created),
			}) {
				break
			}
		}
		return out, rows.Err()
	}

	if root.Node.Kind == pb.NodeKind_NODE_KIND_FILE {
		if root.BlobID != nil {
			rows, err := s.DB.Query(ctx, `SELECT a.id::text,a.path,a.kind,a.size_bytes,a.created_at
				FROM blob_artifacts a WHERE a.blob_id=$1 ORDER BY a.path`, *root.BlobID)
			if err != nil {
				return nil, err
			}
			defer rows.Close()
			for rows.Next() {
				var id, artPath, kind string
				var size int64
				var created time.Time
				if err = rows.Scan(&id, &artPath, &kind, &size, &created); err != nil {
					return nil, err
				}
				nk := pb.NodeKind_NODE_KIND_DIRECTORY
				if kind == "file" {
					nk = pb.NodeKind_NODE_KIND_FILE
				}
				if matchAndAppend(&pb.GlobHit{
					Path:         artPath,
					NodeId:       id,
					Kind:         nk,
					ArtifactPath: artPath,
					SizeBytes:    size,
					UpdatedAt:    timestamppb.New(created),
				}) {
					break
				}
			}
			return out, rows.Err()
		}
		var size int64
		if root.Node.File != nil {
			size = root.Node.File.SizeBytes
		}
		matchAndAppend(&pb.GlobHit{
			Path:      root.Node.Name,
			NodeId:    root.Node.Id,
			Kind:      root.Node.Kind,
			SizeBytes: size,
			UpdatedAt: root.Node.UpdatedAt,
		})
		return out, nil
	}

	rows, err := s.DB.Query(ctx, `WITH RECURSIVE tree AS (
		SELECT n.id,n.kind,''::text AS rel_path,n.updated_at
		FROM nodes n WHERE n.id=$1 AND n.storage_id=$2
		UNION ALL
		SELECT c.id,c.kind,CASE WHEN t.rel_path='' THEN c.name ELSE t.rel_path||'/'||c.name END,c.updated_at
		FROM tree t JOIN nodes c ON c.parent_id=t.id AND c.storage_id=$2
		WHERE t.kind='directory'
	),
	entries AS (
		SELECT t.rel_path,t.id::text AS node_id,t.kind,''::text AS artifact_path,coalesce(f.size_bytes,0) AS size_bytes,t.updated_at
		FROM tree t LEFT JOIN files f ON f.node_id=t.id
		WHERE t.rel_path<>''
		UNION ALL
		SELECT CASE WHEN t.rel_path='' THEN a.path ELSE t.rel_path||'/'||a.path END AS rel_path,
		       a.id::text AS node_id,a.kind,a.path AS artifact_path,a.size_bytes,a.created_at AS updated_at
		FROM tree t
		JOIN files f ON f.node_id=t.id AND f.blob_id IS NOT NULL
		JOIN blob_artifacts a ON a.blob_id=f.blob_id
	)
	SELECT rel_path,node_id,kind,artifact_path,size_bytes,updated_at
	FROM entries
	ORDER BY updated_at DESC, rel_path ASC`,
		root.Node.Id, r.StorageId)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var relPath, nodeID, kind, artPath string
		var size int64
		var updated time.Time
		if err = rows.Scan(&relPath, &nodeID, &kind, &artPath, &size, &updated); err != nil {
			return nil, err
		}
		nk := pb.NodeKind_NODE_KIND_DIRECTORY
		if kind == "file" {
			nk = pb.NodeKind_NODE_KIND_FILE
		}
		if matchAndAppend(&pb.GlobHit{
			Path:         relPath,
			NodeId:       nodeID,
			Kind:         nk,
			ArtifactPath: artPath,
			SizeBytes:    size,
			UpdatedAt:    timestamppb.New(updated),
		}) {
			break
		}
	}
	return out, rows.Err()
}

type lineMatcher struct {
	literal       bool
	caseSensitive bool
	needle        string
	re            *regexp.Regexp
}

func newLineMatcher(pattern string, literal, caseSensitive bool) (*lineMatcher, error) {
	if literal {
		needle := pattern
		if !caseSensitive {
			needle = strings.ToLower(needle)
		}
		return &lineMatcher{literal: true, caseSensitive: caseSensitive, needle: needle}, nil
	}
	expr := pattern
	if !caseSensitive {
		expr = "(?i)" + expr
	}
	re, err := regexp.Compile(expr)
	if err != nil {
		return nil, invalid("invalid regex pattern: " + err.Error())
	}
	return &lineMatcher{re: re, caseSensitive: caseSensitive}, nil
}

func (m *lineMatcher) matchLine(line string) bool {
	if m.literal {
		if m.caseSensitive {
			return strings.Contains(line, m.needle)
		}
		return strings.Contains(strings.ToLower(line), m.needle)
	}
	return m.re.MatchString(line)
}

func extractGrepLines(text, relPath, nodeID, artPath string, matcher *lineMatcher, maxLineChars, limit int, out *pb.GrepResponse) bool {
	for i, raw := range textLines(text) {
		line := strings.TrimRight(raw, "\r\n")
		if !matcher.matchLine(line) {
			continue
		}
		if len(out.Hits) >= limit {
			out.Truncated = true
			return true
		}
		out.Hits = append(out.Hits, &pb.GrepHit{
			Path:         relPath,
			LineNumber:   uint32(i + 1),
			LineText:     clipRunes(line, maxLineChars),
			NodeId:       nodeID,
			ArtifactPath: artPath,
		})
	}
	return false
}

func (s *Server) Grep(ctx context.Context, r *pb.GrepRequest) (*pb.GrepResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	includeGlob := normalizeGlobPattern(r.IncludeGlob)
	if includeGlob != "" && !doublestar.ValidatePattern(includeGlob) {
		return nil, invalid("invalid include_glob pattern")
	}
	matcher, err := newLineMatcher(r.Pattern, r.Literal, r.CaseSensitive)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, s.searchTimeout())
	defer cancel()

	root, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Root, true, false)
	if err != nil {
		return nil, err
	}
	limit := s.effectiveSearchLimit(r.Limit)
	maxLineChars := s.searchMaxLineChars()
	out := new(pb.GrepResponse)

	// Single-file or single-artifact root: scan directly in Go without extra DB round-trip.
	if root.Artifact != nil && root.Artifact.Kind == "file" {
		if root.Text == nil || !matchesIncludeGlob(includeGlob, path.Base(root.Artifact.Path)) {
			return out, nil
		}
		extractGrepLines(*root.Text, ".", root.Node.Id, root.Artifact.Path, matcher, maxLineChars, limit, out)
		return out, nil
	}
	if root.Artifact == nil && root.Node.Kind == pb.NodeKind_NODE_KIND_FILE && root.BlobID == nil {
		if root.Text == nil || !matchesIncludeGlob(includeGlob, root.Node.Name) {
			return out, nil
		}
		extractGrepLines(*root.Text, ".", root.Node.Id, "", matcher, maxLineChars, limit, out)
		return out, nil
	}

	// Build Stage 1 Postgres pg_trgm GIN pre-filter predicate.
	var filterClause string
	var filterArg any
	if r.Literal {
		filterClause = fmt.Sprintf(`text_content %s $3 ESCAPE '\'`, likeOp(r.CaseSensitive))
		filterArg = literalPattern(r.Pattern)
	} else if pgPat, ok := pgSafeRegex(r.Pattern); ok {
		filterClause = fmt.Sprintf(`text_content %s $3`, regexOp(r.CaseSensitive))
		filterArg = pgPat
	} else {
		filterClause = `($3::text IS NOT NULL OR true)`
		filterArg = ""
	}

	var rows pgx.Rows
	switch {
	case root.Artifact != nil:
		rows, err = s.DB.Query(ctx, `SELECT substring(a.path from char_length($4) + 1) AS rel_path,a.id::text,a.path,a.text_content
			FROM blob_artifacts a
			WHERE a.blob_id=$1 AND a.path LIKE $2 ESCAPE '\' AND a.text_content IS NOT NULL AND a.`+filterClause+`
			ORDER BY a.path`,
			root.Artifact.BlobID, prefixPattern(root.Artifact.Path), filterArg, root.Artifact.Path+"/")
	case root.Node.Kind == pb.NodeKind_NODE_KIND_FILE && root.BlobID != nil:
		rows, err = s.DB.Query(ctx, `SELECT a.path AS rel_path,a.id::text,a.path,a.text_content
			FROM blob_artifacts a
			WHERE a.blob_id=$1 AND a.text_content IS NOT NULL AND ($2::text='' OR true) AND a.`+filterClause+`
			ORDER BY a.path`,
			*root.BlobID, "", filterArg)
	default:
		rows, err = s.DB.Query(ctx, `WITH RECURSIVE tree AS (
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
		)
		SELECT rel_path,node_id,artifact_path,text_content FROM (
			SELECT tf.rel_path,tf.node_id::text AS node_id,''::text AS artifact_path,f.text_content
			FROM tree_files tf
			JOIN files f ON f.node_id=tf.node_id
			WHERE tf.has_text AND f.`+filterClause+`
			UNION ALL
			SELECT CASE WHEN tf.rel_path='' THEN a.path ELSE tf.rel_path||'/'||a.path END AS rel_path,
			       a.id::text AS node_id,a.path AS artifact_path,a.text_content
			FROM tree_files tf
			JOIN blob_artifacts a ON a.blob_id=tf.blob_id
			WHERE a.text_content IS NOT NULL AND a.`+filterClause+`
		) candidates
		ORDER BY rel_path`,
			root.Node.Id, r.StorageId, filterArg)
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	for rows.Next() {
		var relPath, nodeID, artPath, textContent string
		if err = rows.Scan(&relPath, &nodeID, &artPath, &textContent); err != nil {
			return nil, err
		}
		if !matchesIncludeGlob(includeGlob, relPath) {
			continue
		}
		if extractGrepLines(textContent, relPath, nodeID, artPath, matcher, maxLineChars, limit, out) {
			break
		}
	}
	return out, rows.Err()
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
	ctx, cancel := context.WithTimeout(ctx, s.semanticTimeout())
	defer cancel()

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
	resultLimit := settings.ResultLimit
	if r.Limit != nil && *r.Limit > 0 {
		resultLimit = min(uint64(*r.Limit), s.semanticMaxResultLimit())
	}
	span.SetAttributes(ragAttributes(ctx)...)
	span.SetAttributes(
		attribute.String("langfuse.observation.type", "retriever"),
		attribute.String("langfuse.observation.input", r.Query),
		attribute.String("langfuse.observation.metadata.storage_id", r.StorageId),
		attribute.Int("langfuse.observation.metadata.result_limit", int(resultLimit)),
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
	prefetchLimit := max(settings.CandidateLimit, resultLimit)
	limit := resultLimit
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
		ranked, err := s.rerank(ctx, r.Query, documents, int(resultLimit))
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

	maxExcerpt := s.semanticMaxExcerptChars()
	result = new(pb.SemanticSearchResponse)
	for _, c := range candidates {
		excerpt := clipRunes(c.text, maxExcerpt)
		for _, ref := range byBlob[c.blobID] {
			result.Hits = append(result.Hits, &pb.SemanticHit{
				FileId:       ref.fileID,
				Path:         ref.path,
				ArtifactPath: c.artPath,
				Text:         excerpt,
				Score:        c.score,
			})
			if uint64(len(result.Hits)) >= resultLimit {
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
