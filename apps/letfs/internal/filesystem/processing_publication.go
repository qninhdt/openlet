package filesystem

import (
	"context"
	"encoding/json"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
)

type ParseManifest struct {
	Uploads     []uuid.UUID `json:"uploads"`
	Directories []string    `json:"directories"`
}

func outputTree(files map[string]uuid.UUID, directories []string, limit int64) (map[string]*uuid.UUID, error) {
	tree := make(map[string]*uuid.UUID)
	explicit := make(map[string]bool)
	add := func(path string, upload *uuid.UUID) error {
		if err := relativeArtifactPath(path); err != nil {
			return err
		}
		if explicit[path] {
			return rpc.Fault(codes.InvalidArgument, "VALIDATION", "duplicate artifact path")
		}
		explicit[path] = true
		if old, exists := tree[path]; exists && (old != nil || upload != nil) {
			return rpc.Fault(codes.InvalidArgument, "VALIDATION", "artifact file/directory collision")
		}
		tree[path] = upload
		for parent := path; ; {
			at := strings.LastIndexByte(parent, '/')
			if at < 0 {
				break
			}
			parent = parent[:at]
			if tree[parent] != nil {
				return rpc.Fault(codes.InvalidArgument, "VALIDATION", "artifact file/directory collision")
			}
			if _, exists := tree[parent]; !exists {
				tree[parent] = nil
			}
		}
		if int64(len(tree)) > limit {
			return uploadState("RESOURCE_LIMIT")
		}
		return nil
	}
	for path, id := range files {
		if err := add(path, &id); err != nil {
			return nil, err
		}
	}
	for _, path := range directories {
		if err := add(path, nil); err != nil {
			return nil, err
		}
	}
	return tree, nil
}

func artifactMediaType(name string) string {
	index := strings.LastIndexByte(name, '.')
	extension := ""
	if index >= 0 {
		extension = strings.ToLower(name[index+1:])
	}
	switch extension {
	case "md", "markdown":
		return "text/markdown"
	case "csv":
		return "text/csv"
	case "json":
		return "application/json"
	case "png":
		return "image/png"
	case "jpg", "jpeg":
		return "image/jpeg"
	case "webp":
		return "image/webp"
	case "gif":
		return "image/gif"
	case "pdf":
		return "application/pdf"
	case "docx":
		return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
	case "xlsx":
		return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
	case "pptx":
		return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
	default:
		return "text/plain"
	}
}

func (s *Store) CompleteParse(ctx context.Context, a Generation, manifest ParseManifest) error {
	if err := a.validate(); err != nil {
		return err
	}
	if int64(len(manifest.Uploads)) > s.ProcessingMaxOutputs || int64(len(manifest.Directories)) > s.ProcessingMaxOutputs {
		return uploadState("RESOURCE_LIMIT")
	}
	session, err := s.processingSession(ctx, a, false)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.currentProcessing(ctx, a)
	if err != nil {
		return err
	}
	if _, err = session.processingSource(ctx, p); err != nil {
		return err
	}
	if p.publication != "pending" {
		return nil
	}
	rows, err := session.tx.Query(ctx, `SELECT id,relative_path,state,result_node_id,expected_size FROM uploads
 WHERE processing_file_id=$1 AND processing_generation=$2 AND id=ANY($3) AND processing_stage='parse' ORDER BY relative_path FOR UPDATE`, a.FileID, a.Generation, manifest.Uploads)
	if err != nil {
		return databaseError(err)
	}
	type output struct {
		id          uuid.UUID
		path, state string
		node        *uuid.UUID
		size        int64
	}
	outputs, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (output, error) {
		var v output
		err := row.Scan(&v.id, &v.path, &v.state, &v.node, &v.size)
		return v, err
	})
	if err != nil {
		return databaseError(err)
	}
	wanted := make(map[uuid.UUID]bool, len(manifest.Uploads))
	for _, id := range manifest.Uploads {
		if wanted[id] {
			return uploadState("OUTPUTS_INCOMPLETE")
		}
		wanted[id] = true
	}
	if len(wanted) != len(outputs) {
		return uploadState("OUTPUTS_INCOMPLETE")
	}
	files := make(map[string]uuid.UUID, len(outputs))
	var bytes int64
	for _, out := range outputs {
		if !wanted[out.id] || out.state != "finalized" || out.node != nil {
			return uploadState("OUTPUTS_INCOMPLETE")
		}
		if out.size > s.ProcessingMaxOutputBytes-bytes {
			return uploadState("RESOURCE_LIMIT")
		}
		bytes += out.size
		if _, exists := files[out.path]; exists {
			return enrichmentValidation("duplicate artifact path")
		}
		files[out.path] = out.id
	}
	tree, err := outputTree(files, manifest.Directories, s.ProcessingMaxOutputs)
	if err != nil {
		return err
	}
	depth, err := session.depth(ctx, a.FileID)
	if err != nil {
		return err
	}
	for path := range tree {
		if depth+1+int64(strings.Count(path, "/")) > maxDepth {
			return uploadState("RESOURCE_LIMIT")
		}
	}
	var children bool
	if err = session.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM nodes WHERE filesystem_id=$1 AND parent_id=$2)`, session.fs, a.FileID).Scan(&children); err != nil {
		return databaseError(err)
	}
	if children {
		return uploadState("PROCESSING_ALREADY_PUBLISHED")
	}
	if err = session.usage(ctx, bytes); err != nil {
		return err
	}
	if err = session.addNodes(ctx, int64(len(tree))); err != nil {
		return err
	}
	ids := make(map[string]uuid.UUID, len(tree))
	for path := range tree {
		ids[path] = uuid.Must(uuid.NewV7())
	}
	type entry struct {
		ID        uuid.UUID  `json:"id"`
		Parent    uuid.UUID  `json:"parent"`
		Name      string     `json:"name"`
		Upload    *uuid.UUID `json:"upload"`
		MediaType string     `json:"media_type"`
	}
	entries := make([]entry, 0, len(tree))
	for path, upload := range tree {
		parent, name := a.FileID, path
		if at := strings.LastIndexByte(path, '/'); at >= 0 {
			parent, name = ids[path[:at]], path[at+1:]
		}
		entries = append(entries, entry{ids[path], parent, name, upload, artifactMediaType(name)})
	}
	encoded, err := json.Marshal(entries)
	if err != nil {
		return err
	}
	_, err = session.tx.Exec(ctx, `WITH entries AS (SELECT * FROM jsonb_to_recordset($2) AS x(id uuid,parent uuid,name text,upload uuid))
 INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) SELECT e.id,$1,e.parent,e.name,CASE WHEN e.upload IS NULL THEN 'directory' ELSE 'file' END,coalesce(u.expected_size,0) FROM entries e LEFT JOIN uploads u ON u.id=e.upload`, session.fs, encoded)
	if err != nil {
		return databaseError(err)
	}
	_, err = session.tx.Exec(ctx, `WITH entries AS (SELECT * FROM jsonb_to_recordset($1) AS x(id uuid,parent uuid,name text,upload uuid,media_type text))
 INSERT INTO files(node_id,storage_kind,inline_bytes,object_key,media_type) SELECT e.id,CASE WHEN u.transport='inline' THEN 'inline' ELSE 'object' END,u.inline_bytes,u.candidate_key,e.media_type FROM entries e JOIN uploads u ON u.id=e.upload`, encoded)
	if err != nil {
		return databaseError(err)
	}
	_, err = session.tx.Exec(ctx, `UPDATE uploads u SET result_node_id=e.id,inline_bytes=NULL,updated_at=now() FROM jsonb_to_recordset($1) AS e(id uuid,parent uuid,name text,upload uuid) WHERE u.id=e.upload`, encoded)
	if err != nil {
		return databaseError(err)
	}
	_, err = session.tx.Exec(ctx, `UPDATE files SET publication_status='parsed',processing_updated_at=now() WHERE node_id=$1`, a.FileID)
	if err != nil {
		return databaseError(err)
	}
	if err = session.discardUploads(ctx, a); err != nil {
		return err
	}
	return databaseError(session.tx.Commit(ctx))
}
