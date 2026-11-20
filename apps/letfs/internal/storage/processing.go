package storage

import (
	"context"
	"encoding/json"
	"mime"
	"path"
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

const sourceCTE = `WITH RECURSIVE source AS (SELECT n.id,n.storage_id,n.parent_id FROM nodes n JOIN files f ON f.node_id=n.id WHERE n.id=$1 AND f.version=$2 AND f.object_key IS NOT NULL),chain AS(SELECT id,storage_id,parent_id,0 AS depth FROM source UNION ALL SELECT n.id,n.storage_id,n.parent_id,c.depth+1 FROM chain c JOIN nodes n ON n.id=c.parent_id),live AS(SELECT src.id,src.storage_id,s.workspace_id,s.allow_indexing FROM source src JOIN storages s ON s.id=src.storage_id WHERE EXISTS(SELECT 1 FROM chain c WHERE c.id=s.root_node_id) AND NOT EXISTS(SELECT 1 FROM chain c JOIN nodes n ON n.id=c.id WHERE c.depth>0 AND n.kind='file')) `

func lockSource(ctx context.Context, tx pgx.Tx, id string, version int64) (string, string, bool, error) {
	var storage, workspace string
	var indexing bool
	err := tx.QueryRow(ctx, sourceCTE+` SELECT l.storage_id,l.workspace_id,l.allow_indexing FROM live l JOIN files f ON f.node_id=l.id AND f.version=$2 FOR UPDATE OF f`, id, version).Scan(&storage, &workspace, &indexing)
	return storage, workspace, indexing, err
}
func obsolete(err error) (*pb.ProcessingOutcome, error) {
	if err == pgx.ErrNoRows {
		return &pb.ProcessingOutcome{Obsolete: true}, nil
	}
	return nil, err
}
func (s *Server) GetProcessingInput(ctx context.Context, r *pb.ProcessingRequest) (*pb.ProcessingInput, error) {
	rows, err := s.DB.Query(ctx, sourceCTE+`,tree AS(SELECT n.id,n.storage_id,''::text AS path,0 AS depth FROM live l JOIN nodes n ON n.id=l.id UNION ALL SELECT n.id,n.storage_id,CASE WHEN t.path='' THEN n.name ELSE t.path||'/'||n.name END,t.depth+1 FROM tree t JOIN nodes n ON n.storage_id=t.storage_id AND n.parent_id=t.id JOIN processing src ON src.file_id=$1 WHERE src.stage IN ('parsed','enriched')) SELECT l.workspace_id,l.storage_id,l.allow_indexing,src.stage,t.id,t.path,t.depth>0 FROM live l JOIN processing src ON src.file_id=l.id JOIN tree t ON true ORDER BY t.depth,t.path`, r.FileId, r.Version)
	if err != nil {
		return nil, err
	}
	out := &pb.ProcessingInput{Outcome: &pb.ProcessingOutcome{Obsolete: true}}
	ids := []string{}
	readonly := []bool{}
	paths := map[string]string{}
	for rows.Next() {
		var id, pth, stage string
		var ro bool
		if err = rows.Scan(&out.WorkspaceId, &out.StorageId, &out.AllowIndexing, &stage, &id, &pth, &ro); err != nil {
			rows.Close()
			return nil, err
		}
		out.Outcome = &pb.ProcessingOutcome{Stage: stage}
		ids = append(ids, id)
		readonly = append(readonly, ro)
		paths[id] = pth
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	if len(ids) == 0 {
		return out, nil
	}
	nodes, err := readNodes(ctx, s.DB, ids, readonly, true)
	if err != nil {
		return nil, err
	}
	for _, v := range nodes {
		node, text, key := v.Node, v.Text, v.ObjectKey
		pth, stage := paths[node.Id], out.Outcome.Stage

		if node.Id == r.FileId {
			out.SourceName = node.Name
			out.MediaType = node.File.MediaType
			out.SourceMetadata = node.File.Metadata
			if key != nil && (stage == "pending" || strings.HasPrefix(out.MediaType, "image/")) {
				presign := s.Presign
				input := &s3.GetObjectInput{Bucket: &s.Bucket, Key: key}
				if s.ProcessingPresign != nil && stage == "pending" && (out.MediaType == pdfMedia || out.MediaType == docxMedia) {
					presign = s.ProcessingPresign
					disposition := mime.FormatMediaType("attachment", map[string]string{"filename": node.Name})
					input.ResponseContentDisposition = &disposition
				}
				signed, err := presign.PresignGetObject(ctx, input, func(o *s3.PresignOptions) { o.Expires = time.Duration(s.Settings.DownloadURLTTLSeconds) * time.Second })
				if err != nil {
					return nil, err
				}
				out.DownloadUrl = signed.URL
			}
			continue
		}
		a := &pb.ProcessingArtifact{Node: node, Path: pth, TextContent: text}
		if key != nil {
			signed, err := s.Presign.PresignGetObject(ctx, &s3.GetObjectInput{Bucket: &s.Bucket, Key: key}, func(o *s3.PresignOptions) { o.Expires = time.Duration(s.Settings.DownloadURLTTLSeconds) * time.Second })
			if err != nil {
				return nil, err
			}
			a.DownloadUrl = signed.URL
		}
		out.Artifacts = append(out.Artifacts, a)
	}
	return out, nil
}
func validArtifactPath(p string) bool {
	if p == "" || strings.HasPrefix(p, "/") || strings.ContainsRune(p, 0) || path.Clean(p) != p {
		return false
	}
	for _, name := range strings.Split(p, "/") {
		if name == ".." || name == "." || len(name) > 255 {
			return false
		}
	}
	return true
}
func (s *Server) PrepareArtifactUploads(ctx context.Context, r *pb.PrepareArtifactUploadsRequest) (*pb.PrepareArtifactUploadsResponse, error) {
	if len(r.Outputs) > s.Settings.Processing.MaxArtifacts {
		return nil, invalid("too many artifacts")
	}
	var storage string
	var stage string
	err := s.DB.QueryRow(ctx, sourceCTE+` SELECT l.storage_id,p.stage FROM live l JOIN processing p ON p.file_id=l.id`, r.FileId, r.Version).Scan(&storage, &stage)
	if err == pgx.ErrNoRows {
		return &pb.PrepareArtifactUploadsResponse{Outcome: &pb.ProcessingOutcome{Obsolete: true}}, nil
	}
	if err != nil {
		return nil, err
	}
	out := &pb.PrepareArtifactUploadsResponse{Outcome: &pb.ProcessingOutcome{Stage: stage}}
	if stage != "pending" {
		return out, nil
	}
	records := make([]map[string]any, 0, len(r.Outputs))
	for _, spec := range r.Outputs {
		if !validArtifactPath(spec.Path) || spec.SizeBytes > s.Settings.Processing.MaxArtifactBlobBytes {
			return nil, invalid("invalid artifact path or blob size")
		}
		media, err := s.fileMedia(spec.Path, sdk.FileBlob)
		if err != nil {
			return nil, err
		}
		id := uuid.NewString()
		key := "objects/" + id
		transfer, err := s.signedPut(ctx, key, media, spec.Checksum, spec.SizeBytes, time.Duration(s.Settings.UploadURLTTLSeconds)*time.Second)
		if err != nil {
			return nil, err
		}
		out.Uploads = append(out.Uploads, &pb.ArtifactUpload{Path: spec.Path, UploadId: id, PutUrl: transfer.PutUrl, Headers: transfer.Headers})
		records = append(records, map[string]any{"id": id, "key": key, "size": spec.SizeBytes, "media": media, "checksum": spec.Checksum})
	}
	raw, err := json.Marshal(records)
	if err != nil {
		return nil, err
	}
	_, err = s.DB.Exec(ctx, `INSERT INTO uploads(id,storage_id,object_key,size_bytes,media_type,checksum,source_file_id,source_version,expires_at) SELECT x.id,$2,x.key,x.size,x.media,x.checksum,$3,$4,$5 FROM jsonb_to_recordset($1::jsonb) x(id uuid,key text,size bigint,media text,checksum text)`, raw, storage, r.FileId, r.Version, time.Now().Add(time.Duration(s.Settings.UploadURLTTLSeconds)*time.Second))
	return out, err
}
func (s *Server) artifactRecords(source string, artifacts []*pb.Artifact) ([]byte, int, error) {
	if len(artifacts) > s.Settings.Processing.MaxArtifacts {
		return nil, 0, invalid("too many artifacts")
	}
	ids := map[string]string{"": source}
	kinds := map[string]bool{"": true}
	for _, a := range artifacts {
		if !validArtifactPath(a.Path) || ids[a.Path] != "" {
			return nil, 0, invalid("invalid or duplicate artifact path")
		}
		ids[a.Path] = uuid.NewString()
		kinds[a.Path] = a.GetDirectory() != nil
	}
	rows := []map[string]any{}
	handles := 0
	var total int64
	for _, a := range artifacts {
		parentPath := path.Dir(a.Path)
		if parentPath == "." {
			parentPath = ""
		}
		parent := ids[parentPath]
		if parent == "" || !kinds[parentPath] {
			return nil, 0, invalid("artifact parent must be a declared directory")
		}
		v := map[string]any{"id": ids[a.Path], "parent": parent, "name": path.Base(a.Path), "kind": "directory"}
		switch c := a.Content.(type) {
		case *pb.Artifact_Directory:
		case *pb.Artifact_Text:
			media, err := s.fileMedia(a.Path, sdk.FileText)
			if err != nil {
				return nil, 0, err
			}
			if !utf8.ValidString(c.Text.Content) || strings.ContainsRune(c.Text.Content, 0) {
				return nil, 0, invalid("artifact text must be UTF-8 without NUL")
			}
			total += int64(len(c.Text.Content))
			v["kind"] = "file"
			v["text"] = c.Text.Content
			v["media"] = media
		case *pb.Artifact_UploadId:
			if _, err := s.fileMedia(a.Path, sdk.FileBlob); err != nil {
				return nil, 0, err
			}
			v["kind"] = "file"
			v["upload"] = c.UploadId
			handles++
		default:
			return nil, 0, invalid("artifact content is required")
		}
		rows = append(rows, v)
	}
	if total > s.Settings.Processing.MaxManifestTextBytes {
		return nil, 0, invalid("artifact text manifest exceeds limit")
	}
	raw, err := json.Marshal(rows)
	return raw, handles, err
}
func (s *Server) CommitParse(ctx context.Context, r *pb.CommitParseRequest) (*pb.ProcessingOutcome, error) {
	records, expected, err := s.artifactRecords(r.FileId, r.Artifacts)
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	storage, workspace, _, err := lockSource(ctx, tx, r.FileId, r.Version)
	if err != nil {
		return obsolete(err)
	}
	var stage string
	var bytes int64
	var handles int
	var admitted bool
	err = tx.QueryRow(ctx, `WITH admitted AS(UPDATE processing SET stage='parsed',error_code=NULL WHERE file_id=$1 AND stage='pending' RETURNING stage),
 input AS(SELECT * FROM jsonb_to_recordset($4::jsonb) x(id uuid,parent uuid,name text,kind text,text text,media text,upload uuid)),
 handles AS(DELETE FROM uploads u USING input x WHERE EXISTS(SELECT 1 FROM admitted) AND u.id=x.upload AND u.source_file_id=$1 AND u.source_version=$2 AND u.storage_id=$3 AND u.expires_at>now() AND u.result IS NULL RETURNING u.id,u.object_key,u.size_bytes,u.media_type),
 inserted AS(INSERT INTO nodes(id,storage_id,parent_id,name,kind) SELECT id,$3,parent,name,kind FROM input WHERE EXISTS(SELECT 1 FROM admitted) RETURNING id),
 payload AS(INSERT INTO files(node_id,version,size_bytes,media_type,text_content,object_key) SELECT x.id,1,CASE WHEN x.text IS NOT NULL THEN octet_length(x.text) ELSE h.size_bytes END,coalesce(x.media,h.media_type),x.text,h.object_key FROM input x JOIN inserted n ON n.id=x.id LEFT JOIN handles h ON h.id=x.upload WHERE x.kind='file' AND (x.upload IS NULL OR h.id IS NOT NULL) RETURNING size_bytes)
 SELECT coalesce((SELECT stage FROM admitted),(SELECT stage FROM processing WHERE file_id=$1)),(SELECT coalesce(sum(size_bytes),0) FROM payload),(SELECT count(*) FROM handles),EXISTS(SELECT 1 FROM admitted)`, r.FileId, r.Version, storage, records).Scan(&stage, &bytes, &handles, &admitted)
	if err != nil {
		return nil, err
	}
	if admitted && handles != expected {
		return nil, invalid("artifact handles are expired or belong to another source/version")
	}
	if err = s.quota(ctx, tx, workspace, bytes); err != nil {
		return nil, err
	}
	return &pb.ProcessingOutcome{Stage: stage}, tx.Commit(ctx)
}
func (s *Server) CommitEnrichment(ctx context.Context, r *pb.CommitEnrichmentRequest) (*pb.ProcessingOutcome, error) {
	if len(r.Artifacts) > s.Settings.Processing.MaxArtifacts {
		return nil, invalid("too many enriched artifacts")
	}
	records := []map[string]any{}
	var total int64
	for _, a := range r.Artifacts {
		v := map[string]any{"id": a.NodeId}
		if a.Name != nil {
			if !validArtifactPath(*a.Name) || strings.Contains(*a.Name, "/") {
				return nil, invalid("invalid artifact name")
			}
			v["name"] = *a.Name
		}
		if a.TextContent != nil {
			if !utf8.ValidString(*a.TextContent) || strings.ContainsRune(*a.TextContent, 0) {
				return nil, invalid("invalid artifact text")
			}
			total += int64(len(*a.TextContent))
			v["text"] = *a.TextContent
		}
		if a.Metadata != nil {
			v["metadata"] = map[string]any{"title": a.Metadata.Title, "description": a.Metadata.Description, "semantic_type": a.Metadata.SemanticType, "context": a.Metadata.Context}
		}
		records = append(records, v)
	}
	if total > s.Settings.Processing.MaxManifestTextBytes {
		return nil, invalid("enrichment manifest exceeds limit")
	}
	raw, err := json.Marshal(records)
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	_, workspace, _, err := lockSource(ctx, tx, r.FileId, r.Version)
	if err != nil {
		return obsolete(err)
	}
	// Defer only this batch: a final name can still belong to a sibling that is also being renamed.
	if _, err = tx.Exec(ctx, `SET CONSTRAINTS nodes_sibling DEFERRED`); err != nil {
		return nil, err
	}
	var stage string
	var bytes int64
	var count int
	var admitted bool
	err = tx.QueryRow(ctx, `WITH RECURSIVE tree AS(SELECT id FROM nodes WHERE parent_id=$1 UNION ALL SELECT n.id FROM nodes n JOIN tree t ON n.parent_id=t.id),
 admitted AS(UPDATE processing SET stage='enriched',error_code=NULL WHERE file_id=$1 AND stage='parsed' RETURNING stage),
 input AS(SELECT x.* FROM jsonb_to_recordset($2::jsonb) x(id uuid,name text,text text,metadata jsonb)),
 valid AS MATERIALIZED(SELECT x.*,f.size_bytes AS old_size FROM input x JOIN tree t ON t.id=x.id JOIN nodes n ON n.id=x.id LEFT JOIN files f ON f.node_id=x.id WHERE (n.kind='file' OR (x.text IS NULL AND x.metadata IS NULL)) AND (x.text IS NULL OR f.text_content IS NOT NULL)),
 changed AS(UPDATE files f SET text_content=v.text,size_bytes=octet_length(v.text),version=f.version+1 FROM valid v WHERE f.node_id=v.id AND v.text IS NOT NULL AND f.text_content IS DISTINCT FROM v.text AND EXISTS(SELECT 1 FROM admitted) RETURNING f.node_id,f.size_bytes-v.old_size AS delta),
 touched AS(UPDATE nodes n SET name=coalesce(v.name,n.name),updated_at=now() FROM valid v WHERE n.id=v.id AND EXISTS(SELECT 1 FROM admitted) AND (n.name IS DISTINCT FROM coalesce(v.name,n.name) OR n.id IN (SELECT node_id FROM changed))),
 metadata AS(INSERT INTO file_metadata(node_id,title,description,semantic_type,context) SELECT id,metadata->>'title',metadata->>'description',metadata->>'semantic_type',metadata->>'context' FROM valid WHERE metadata IS NOT NULL AND EXISTS(SELECT 1 FROM admitted) ON CONFLICT(node_id) DO UPDATE SET title=excluded.title,description=excluded.description,semantic_type=excluded.semantic_type,context=excluded.context)
 SELECT coalesce((SELECT stage FROM admitted),(SELECT stage FROM processing WHERE file_id=$1)),(SELECT coalesce(sum(delta),0) FROM changed),(SELECT count(DISTINCT id) FROM valid),EXISTS(SELECT 1 FROM admitted)`, r.FileId, raw).Scan(&stage, &bytes, &count, &admitted)
	if err != nil {
		return nil, err
	}
	if admitted && count != len(r.Artifacts) {
		return nil, invalid("enrichment contains invalid or stale artifact IDs")
	}
	if admitted && r.SourceMetadata != nil {
		m := r.SourceMetadata
		if _, err = tx.Exec(ctx, `INSERT INTO file_metadata(node_id,title,description,semantic_type,context) VALUES($1,$2,$3,$4,$5) ON CONFLICT(node_id) DO UPDATE SET title=excluded.title,description=excluded.description,semantic_type=excluded.semantic_type,context=excluded.context`, r.FileId, m.Title, m.Description, m.SemanticType, m.Context); err != nil {
			return nil, err
		}
	}
	if err = s.quota(ctx, tx, workspace, bytes); err != nil {
		return nil, err
	}
	return &pb.ProcessingOutcome{Stage: stage}, tx.Commit(ctx)
}
func (s *Server) CompleteIndex(ctx context.Context, r *pb.ProcessingRequest) (*pb.ProcessingOutcome, error) {
	return s.finishProcessing(ctx, r.FileId, r.Version, "", nil)
}
func (s *Server) FailProcessing(ctx context.Context, r *pb.FailProcessingRequest) (*pb.ProcessingOutcome, error) {
	return s.finishProcessing(ctx, r.FileId, r.Version, r.ErrorCode, &r.Attempt)
}
func (s *Server) finishProcessing(ctx context.Context, id string, version int64, code string, attempt *int64) (*pb.ProcessingOutcome, error) {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	if _, _, _, err = lockSource(ctx, tx, id, version); err != nil {
		return obsolete(err)
	}
	var stage string
	err = tx.QueryRow(ctx, `UPDATE processing SET stage=CASE WHEN $2='' AND stage='enriched' THEN 'ready' ELSE stage END,error_code=CASE WHEN stage='ready' OR $2='' THEN NULL ELSE $2 END WHERE file_id=$1 AND ($3::bigint IS NULL OR attempt=$3) RETURNING stage`, id, code, attempt).Scan(&stage)
	if err != nil {
		return obsolete(err)
	}
	return &pb.ProcessingOutcome{Stage: stage}, tx.Commit(ctx)
}

func resetProcessing(ctx context.Context, tx pgx.Tx, r *pb.RetryProcessingRequest) (*pb.Node, error) {
	current, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, r.Target, false, true)
	if err != nil {
		return nil, err
	}
	if err = writable(current); err != nil {
		return nil, err
	}
	if current.Node.File == nil || current.Node.File.Type != pb.FileType_FILE_TYPE_BLOB {
		return nil, status.Error(codes.FailedPrecondition, "only source blob files can be reprocessed")
	}
	if current.Node.File.Version != r.ExpectedVersion {
		return nil, conflict("content version changed")
	}
	tag, err := tx.Exec(ctx, `UPDATE processing SET attempt=attempt+1,error_code=NULL WHERE file_id=$1 AND error_code IS NOT NULL AND stage<>'ready'`, current.Node.Id)
	if err != nil {
		return nil, err
	}
	if tag.RowsAffected() != 1 {
		return nil, status.Error(codes.FailedPrecondition, "only failed processing can be retried")
	}
	current.Node.File.Processing.ErrorCode = nil
	return current.Node, nil
}

func (s *Server) RetryProcessing(ctx context.Context, r *pb.RetryProcessingRequest) (*pb.Node, error) {
	actor, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(pb.Node)
	duplicate, err := sdk.Claim(ctx, tx, actor.String(), "RetryProcessing", r.RequestId, r, out, s.ttl())
	if err != nil {
		return nil, err
	}
	if !duplicate {
		out, err = resetProcessing(ctx, tx, r)
		if err != nil {
			return nil, err
		}
		if err = sdk.Finish(ctx, tx, actor.String(), "RetryProcessing", r.RequestId, out); err != nil {
			return nil, err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	// Maintenance recovers dispatch if the service stops after committing the retry.
	if err = s.dispatch(ctx, out.Id, out.File.Version, requiresParse(out.File.MediaType)); err != nil {
		return nil, err
	}
	return out, nil
}
