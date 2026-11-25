package storage

import (
	"context"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func (s *Server) GetBlobArtifacts(ctx context.Context, r *pb.BlobRequest) (*pb.GetBlobArtifactsResponse, error) {
	out := &pb.GetBlobArtifactsResponse{Outcome: &pb.BlobProcessingOutcome{Obsolete: true}}
	var stage string
	err := s.DB.QueryRow(ctx, `SELECT workspace_id::text,id::text,object_key,media_type,source_name,size_bytes,checksum,coalesce(processing_stage,''),title,description FROM blobs WHERE id=$1 AND delete_requested_at IS NULL`, r.BlobId).Scan(
		&out.WorkspaceId, &out.BlobId, &out.ObjectKey, &out.MediaType, &out.SourceName, &out.SizeBytes, &out.Checksum, &stage, &out.Title, &out.Description,
	)
	if err == pgx.ErrNoRows {
		return out, nil
	}
	if err != nil {
		return nil, err
	}
	out.Outcome = &pb.BlobProcessingOutcome{Stage: stage}
	if s.ProcessingPresign != nil && out.ObjectKey != "" {
		url, err := s.ProcessingPresign.PresignGetObject(ctx, &s3.GetObjectInput{Bucket: &s.Bucket, Key: &out.ObjectKey}, func(o *s3.PresignOptions) {
			o.Expires = time.Duration(s.Settings.DownloadURLTTLSeconds) * time.Second
		})
		if err != nil {
			return nil, err
		}
		out.SourceDownloadUrl = url.URL
	}
	rows, err := s.DB.Query(ctx, `SELECT id::text,blob_id::text,path,parent_path,kind,media_type,size_bytes,checksum,object_key,text_content,title,description,indexable FROM blob_artifacts WHERE blob_id=$1 ORDER BY path`, r.BlobId)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var a pb.BlobArtifact
		var kind, checksum string
		var objKey, textContent *string
		if err = rows.Scan(&a.Id, &a.BlobId, &a.Path, &a.ParentPath, &kind, &a.MediaType, &a.SizeBytes, &checksum, &objKey, &textContent, &a.Title, &a.Description, &a.Indexable); err != nil {
			return nil, err
		}
		if kind == "directory" {
			a.Kind = pb.NodeKind_NODE_KIND_DIRECTORY
		} else {
			a.Kind = pb.NodeKind_NODE_KIND_FILE
		}
		a.Checksum = nonEmptyPtr(checksum)
		a.ObjectKey = objKey
		a.TextContent = textContent
		out.Artifacts = append(out.Artifacts, &a)
	}
	return out, rows.Err()
}

type parsedRow struct {
	id          string
	path        string
	parentPath  string
	kind        string
	mediaType   string
	sizeBytes   int64
	checksum    string
	objectKey   *string
	textContent *string
	title       string
	description string
	indexable   bool
}

func (s *Server) normalizeParsedArtifacts(items []*pb.ParsedArtifactInput) ([]parsedRow, error) {
	byPath := make(map[string]parsedRow, len(items))
	var textBytes int64
	for _, item := range items {
		cleaned, ok := cleanArtifactPath(item.Path)
		if !ok {
			return nil, invalid("invalid artifact path")
		}
		if _, exists := byPath[cleaned]; exists {
			return nil, invalid("duplicate artifact path")
		}
		row := parsedRow{
			id:          uuid.NewString(),
			path:        cleaned,
			parentPath:  artifactParentPath(cleaned),
			mediaType:   item.MediaType,
			sizeBytes:   item.SizeBytes,
			checksum:    item.GetChecksum(),
			title:       item.GetTitle(),
			description: item.GetDescription(),
			indexable:   item.Indexable,
		}
		if item.Kind == pb.NodeKind_NODE_KIND_DIRECTORY {
			if item.TextContent != nil || item.ObjectKey != nil {
				return nil, invalid("directory artifact cannot have content")
			}
			row.kind = "directory"
			row.sizeBytes = 0
		} else {
			row.kind = "file"
			hasText := item.TextContent != nil
			hasObj := item.ObjectKey != nil
			if hasText == hasObj {
				return nil, invalid("file artifact must have exactly one of text_content or object_key")
			}
			if hasText {
				if err := s.validateText(*item.TextContent); err != nil {
					return nil, invalid("invalid UTF-8 text artifact or size exceeded")
				}
				row.sizeBytes = int64(len(*item.TextContent))
				textBytes += row.sizeBytes
				row.textContent = item.TextContent
			} else {
				row.objectKey = item.ObjectKey
			}
		}
		byPath[cleaned] = row
	}
	if textBytes > s.Settings.Processing.MaxManifestTextBytes {
		return nil, invalid("artifact text limit exceeded")
	}
	// Synthesize missing parent directory nodes bottom-up.
	for p := range byPath {
		for cur := artifactParentPath(p); cur != ""; cur = artifactParentPath(cur) {
			if existing, ok := byPath[cur]; ok {
				if existing.kind != "directory" {
					return nil, invalid("artifact parent cannot be a file")
				}
				break
			}
			byPath[cur] = parsedRow{
				id:         uuid.NewString(),
				path:       cur,
				parentPath: artifactParentPath(cur),
				kind:       "directory",
			}
		}
	}
	if len(byPath) > s.Settings.Processing.MaxArtifacts {
		return nil, invalid("artifact count limit exceeded")
	}
	out := make([]parsedRow, 0, len(byPath))
	for _, r := range byPath {
		out = append(out, r)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].path < out[j].path })
	return out, nil
}

func (s *Server) SaveParsedArtifacts(ctx context.Context, r *pb.SaveParsedArtifactsRequest) (*pb.BlobProcessingOutcome, error) {
	rows, err := s.normalizeParsedArtifacts(r.Artifacts)
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	var stage *string
	var delAt any
	err = tx.QueryRow(ctx, `SELECT processing_stage,delete_requested_at FROM blobs WHERE id=$1 FOR UPDATE`, r.BlobId).Scan(&stage, &delAt)
	if err == pgx.ErrNoRows || delAt != nil {
		return &pb.BlobProcessingOutcome{Obsolete: true}, nil
	}
	if err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM blob_artifacts WHERE blob_id=$1`, r.BlobId); err != nil {
		return nil, err
	}
	if len(rows) > 0 {
		ids := make([]string, len(rows))
		paths := make([]string, len(rows))
		parents := make([]string, len(rows))
		kinds := make([]string, len(rows))
		medias := make([]string, len(rows))
		sizes := make([]int64, len(rows))
		checksums := make([]string, len(rows))
		keys := make([]*string, len(rows))
		texts := make([]*string, len(rows))
		titles := make([]string, len(rows))
		descs := make([]string, len(rows))
		indexables := make([]bool, len(rows))
		for i, item := range rows {
			ids[i], paths[i], parents[i], kinds[i] = item.id, item.path, item.parentPath, item.kind
			medias[i], sizes[i], checksums[i] = item.mediaType, item.sizeBytes, item.checksum
			keys[i], texts[i] = item.objectKey, item.textContent
			titles[i], descs[i], indexables[i] = item.title, item.description, item.indexable
		}
		_, err = tx.Exec(ctx, `INSERT INTO blob_artifacts(id,blob_id,path,parent_path,kind,media_type,size_bytes,checksum,object_key,text_content,title,description,indexable)
			SELECT v.id,$1,v.path,v.parent_path,v.kind,v.media_type,v.size_bytes,v.checksum,v.object_key,v.text_content,v.title,v.description,v.indexable
			FROM unnest($2::uuid[],$3::text[],$4::text[],$5::text[],$6::text[],$7::bigint[],$8::text[],$9::text[],$10::text[],$11::text[],$12::text[],$13::boolean[])
			AS v(id,path,parent_path,kind,media_type,size_bytes,checksum,object_key,text_content,title,description,indexable)`,
			r.BlobId, ids, paths, parents, kinds, medias, sizes, checksums, keys, texts, titles, descs, indexables)
		if err != nil {
			return nil, err
		}
	}
	if _, err = tx.Exec(ctx, `UPDATE blobs SET processing_stage='parsed',processing_error_code='' WHERE id=$1`, r.BlobId); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	return &pb.BlobProcessingOutcome{Stage: "parsed"}, nil
}

func (s *Server) SaveEnrichedArtifacts(ctx context.Context, r *pb.SaveEnrichedArtifactsRequest) (*pb.BlobProcessingOutcome, error) {
	for _, a := range r.Artifacts {
		if a.Path != nil {
			if _, ok := cleanArtifactPath(*a.Path); !ok {
				return nil, invalid("invalid artifact path")
			}
		}
		if a.TextContent != nil {
			if !utf8.ValidString(*a.TextContent) || strings.ContainsRune(*a.TextContent, 0) {
				return nil, invalid("invalid UTF-8 text artifact")
			}
			if int64(len(*a.TextContent)) > s.Settings.MaxTextBytes {
				return nil, invalid("artifact text limit exceeded")
			}
		}
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	var stage *string
	var delAt any
	err = tx.QueryRow(ctx, `SELECT processing_stage,delete_requested_at FROM blobs WHERE id=$1 FOR UPDATE`, r.BlobId).Scan(&stage, &delAt)
	if err == pgx.ErrNoRows || delAt != nil {
		return &pb.BlobProcessingOutcome{Obsolete: true}, nil
	}
	if err != nil {
		return nil, err
	}
	if stage != nil && *stage == "ready" {
		return &pb.BlobProcessingOutcome{Stage: "ready"}, tx.Commit(ctx)
	}
	if r.BlobTitle != nil || r.BlobDescription != nil {
		if _, err = tx.Exec(ctx, `UPDATE blobs SET title=coalesce($2,title),description=coalesce($3,description) WHERE id=$1`, r.BlobId, r.BlobTitle, r.BlobDescription); err != nil {
			return nil, err
		}
	}
	for _, a := range r.Artifacts {
		var newPath, newParent *string
		if a.Path != nil {
			cleaned, _ := cleanArtifactPath(*a.Path)
			parent := artifactParentPath(cleaned)
			newPath = &cleaned
			newParent = &parent
		}
		tag, err := tx.Exec(ctx, `UPDATE blob_artifacts
			SET path=coalesce($3,path),
			    parent_path=coalesce($4,parent_path),
			    text_content=coalesce($5,text_content),
			    size_bytes=CASE WHEN $5::text IS NOT NULL THEN octet_length($5::text) ELSE size_bytes END,
			    title=coalesce($6,title),
			    description=coalesce($7,description)
			WHERE id=$1 AND blob_id=$2`,
			a.ArtifactId, r.BlobId, newPath, newParent, a.TextContent, a.Title, a.Description)
		if err != nil {
			return nil, err
		}
		if tag.RowsAffected() != 1 {
			return nil, invalid("artifact does not belong to blob")
		}
	}
	var totalText int64
	if err = tx.QueryRow(ctx, `SELECT coalesce(sum(octet_length(text_content)),0) FROM blob_artifacts WHERE blob_id=$1`, r.BlobId).Scan(&totalText); err != nil {
		return nil, err
	}
	if totalText > s.Settings.Processing.MaxManifestTextBytes {
		return nil, invalid("artifact text limit exceeded")
	}
	if _, err = tx.Exec(ctx, `UPDATE blobs SET processing_stage='enriched',processing_error_code='' WHERE id=$1`, r.BlobId); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return &pb.BlobProcessingOutcome{Obsolete: false}, err
	}
	return &pb.BlobProcessingOutcome{Stage: "enriched"}, nil
}

func (s *Server) CompleteBlobIndex(ctx context.Context, r *pb.BlobRequest) (*pb.BlobProcessingOutcome, error) {
	var stage string
	err := s.DB.QueryRow(ctx, `UPDATE blobs SET processing_stage='ready',processing_error_code='' WHERE id=$1 AND delete_requested_at IS NULL AND processing_stage IN ('parsed','enriched','ready') RETURNING processing_stage`, r.BlobId).Scan(&stage)
	if err == pgx.ErrNoRows {
		return &pb.BlobProcessingOutcome{Obsolete: true}, nil
	}
	if err != nil {
		return nil, err
	}
	return &pb.BlobProcessingOutcome{Stage: stage}, nil
}

func (s *Server) RetryProcessing(ctx context.Context, r *pb.RetryProcessingRequest) (*pb.Node, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(pb.Node)
	duplicate, err := sdk.Claim(ctx, tx, a.String(), "RetryProcessing", r.RequestId, r, out, s.ttl())
	if err != nil {
		return nil, err
	}
	if duplicate {
		return out, tx.Commit(ctx)
	}
	current, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, r.Target, false, true)
	if err != nil {
		return nil, err
	}
	if err = writable(current); err != nil {
		return nil, err
	}
	if current.Node.Kind != pb.NodeKind_NODE_KIND_FILE || current.BlobID == nil || current.Node.File.Version != r.ExpectedVersion {
		return nil, conflict("file version has changed")
	}
	var stage, errCode, media string
	var attempt int64
	err = tx.QueryRow(ctx, `SELECT coalesce(processing_stage,''),processing_error_code,processing_attempt,media_type FROM blobs WHERE id=$1 FOR UPDATE`, *current.BlobID).Scan(&stage, &errCode, &attempt, &media)
	if err != nil {
		return nil, err
	}
	if stage != "failed" && errCode == "" {
		return nil, status.Error(codes.FailedPrecondition, "file processing has not failed")
	}
	nextStage := processingStage(media)
	err = tx.QueryRow(ctx, `UPDATE blobs SET processing_stage=$2,processing_error_code='',processing_attempt=processing_attempt+1 WHERE id=$1 RETURNING processing_attempt`, *current.BlobID, nextStage).Scan(&attempt)
	if err != nil {
		return nil, err
	}
	nodes, err := readNodes(ctx, tx, []string{current.Node.Id}, []bool{false}, false)
	if err != nil || len(nodes) == 0 {
		return nil, err
	}
	out = nodes[0].Node
	if err = sdk.Finish(ctx, tx, a.String(), "RetryProcessing", r.RequestId, out); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	if err = s.dispatchBlob(ctx, *current.BlobID, requiresParse(media), attempt); err != nil {
		return nil, err
	}
	return out, nil
}
