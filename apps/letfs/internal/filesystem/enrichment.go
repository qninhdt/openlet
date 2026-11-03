package filesystem

import (
	"context"
	"path"
	"slices"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/apps/letfs/internal/storage"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
)

type SemanticMetadata struct {
	Title        string `json:"title"`
	Description  string `json:"description"`
	SemanticType string `json:"type"`
	Context      string `json:"context"`
}

func enrichmentValidation(message string) error {
	return rpc.Fault(codes.InvalidArgument, "VALIDATION", message)
}

func (m SemanticMetadata) validate() error {
	for _, field := range []struct {
		text  string
		limit int
	}{{m.Title, 200}, {m.Description, 600}, {m.Context, 3000}} {
		if !utf8.ValidString(field.text) || strings.TrimSpace(field.text) == "" || utf8.RuneCountInString(field.text) > field.limit || strings.ContainsRune(field.text, 0) {
			return enrichmentValidation("invalid semantic metadata")
		}
	}
	family, kind, ok := strings.Cut(m.SemanticType, ":")
	allowed := ""
	switch family {
	case "document":
		allowed = "research_paper report article book manual contract other"
	case "text":
		allowed = "content summary notes overview transcript other"
	case "image":
		allowed = "photo screenshot chart diagram illustration other"
	case "table":
		allowed = "records summary time_series other"
	case "spreadsheet":
		allowed = "dataset financial tracker other"
	case "presentation":
		allowed = "lecture pitch report other"
	case "code":
		allowed = "source configuration notebook other"
	case "other":
		allowed = "unknown"
	}
	if !ok || !slices.Contains(strings.Fields(allowed), kind) {
		return enrichmentValidation("invalid semantic type")
	}
	return nil
}

type ProcessingNode struct {
	Node
	Path      string
	Content   *Download
	objectKey *string
}

type EnrichmentPreparation struct {
	SourceID uuid.UUID
	Nodes    []ProcessingNode
	Complete bool
}

type EnrichmentUpdate struct {
	ID       uuid.UUID         `json:"id"`
	Path     string            `json:"path"`
	Metadata *SemanticMetadata `json:"metadata"`
	UploadID *uuid.UUID        `json:"upload_id"`
}

type EnrichmentManifest struct {
	Nodes []EnrichmentUpdate `json:"nodes"`
}

func (s *session) inventory(ctx context.Context, source uuid.UUID, limit int64) ([]ProcessingNode, error) {
	rows, err := s.tx.Query(ctx, `WITH RECURSIVE tree AS (
 SELECT n.*,''::text COLLATE "C" AS path,0 AS depth FROM nodes n WHERE n.id=$1 AND n.filesystem_id=$2
 UNION ALL SELECT n.*,CASE WHEN t.path='' THEN n.name ELSE t.path||'/'||n.name END,t.depth+1
 FROM nodes n JOIN tree t ON n.parent_id=t.id WHERE n.filesystem_id=$2 AND t.depth<128)
 SELECT `+nodeColumns+`,false,n.path,f.inline_bytes,f.object_key FROM tree n LEFT JOIN files f ON f.node_id=n.id ORDER BY n.depth,n.path LIMIT $3`, source, s.fs, limit+2)
	if err != nil {
		return nil, databaseError(err)
	}
	nodes, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (ProcessingNode, error) {
		var node ProcessingNode
		var content []byte
		err := row.Scan(append(node.fields(), &node.Path, &content, &node.objectKey)...)
		if err == nil && node.Kind == "file" {
			if node.MediaType == nil {
				mime := artifactMediaType(node.Name)
				node.MediaType = &mime
			}
			node.Content = &Download{InlineContent: content, SizeBytes: node.SizeBytes}
		}
		return node, err
	})
	if err != nil {
		return nil, databaseError(err)
	}
	if int64(len(nodes)) > limit+1 {
		return nil, uploadState("RESOURCE_LIMIT")
	}
	if len(nodes) > 1 {
		nodes[0].Content = nil
		nodes[0].objectKey = nil
	}
	return nodes, nil
}

func (s *Store) signInventory(ctx context.Context, nodes []ProcessingNode) error {
	for i := range nodes {
		node := &nodes[i]
		if node.Content == nil || node.objectKey == nil {
			continue
		}
		if s.Storage == nil {
			return storageError(ctx, storage.ErrUnavailable)
		}
		signed, err := s.Storage.ProcessorDownloadURL(ctx, *node.objectKey, "evidence", s.DownloadLifetime)
		if err != nil {
			return storageError(ctx, err)
		}
		node.Content.SignedURL = signed
	}
	return nil
}

func (s *session) enrichmentState(ctx context.Context, source Generation) (processingState, error) {
	p, err := s.currentProcessing(ctx, source)
	if err != nil {
		return p, err
	}
	if _, err = s.processingSource(ctx, p); err != nil {
		return p, err
	}
	if p.publication != "parsed" && p.publication != "enriched" && p.publication != "ready" && p.publication != "index_failed" {
		return p, uploadState("PARSE_NOT_COMPLETE")
	}
	return p, nil
}

func (s *Store) PrepareEnrichment(ctx context.Context, a Generation) (EnrichmentPreparation, error) {
	if err := a.validate(); err != nil {
		return EnrichmentPreparation{}, err
	}
	session, err := s.processingSession(ctx, a, false)
	if err != nil {
		return EnrichmentPreparation{}, err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.enrichmentState(ctx, a)
	if err != nil {
		return EnrichmentPreparation{}, err
	}
	result := EnrichmentPreparation{SourceID: a.FileID, Complete: p.publication != "parsed"}
	if result.Complete {
		return result, nil
	}
	result.Nodes, err = session.inventory(ctx, a.FileID, s.ProcessingMaxOutputs)
	if err != nil {
		return result, err
	}
	if err = session.tx.Commit(ctx); err != nil {
		return result, databaseError(err)
	}
	return result, s.signInventory(ctx, result.Nodes)
}

func (s *Store) PrepareEnrichmentOutput(ctx context.Context, a Generation, output ProcessingOutput) (Upload, error) {
	return s.prepareProcessingOutput(ctx, a, "enrichment", output)
}

func validateEnrichment(nodes []ProcessingNode, manifest EnrichmentManifest, source uuid.UUID) (map[uuid.UUID]EnrichmentUpdate, error) {
	updates := make(map[uuid.UUID]EnrichmentUpdate, len(manifest.Nodes))
	for _, update := range manifest.Nodes {
		updates[update.ID] = update
	}
	if len(updates) != len(manifest.Nodes) || len(nodes) != len(manifest.Nodes) {
		return nil, enrichmentValidation("incomplete enrichment manifest")
	}
	paths := make(map[string]bool, len(nodes))
	for _, node := range nodes {
		update, ok := updates[node.ID]
		if !ok {
			return nil, enrichmentValidation("unknown enrichment node")
		}
		if node.Kind == "directory" {
			if update.Metadata != nil {
				return nil, enrichmentValidation("directory cannot own semantic metadata")
			}
		} else {
			if update.Metadata == nil {
				return nil, enrichmentValidation("file metadata required")
			}
			if err := update.Metadata.validate(); err != nil {
				return nil, err
			}
		}
		if paths[update.Path] {
			return nil, enrichmentValidation("duplicate enrichment path")
		}
		paths[update.Path] = true
		if node.ID == source {
			if update.Path != "" || update.UploadID != nil {
				return nil, enrichmentValidation("original file is immutable")
			}
			continue
		}
		if err := relativeArtifactPath(update.Path); err != nil {
			return nil, err
		}
		if node.ParentID == nil {
			return nil, enrichmentValidation("missing enrichment parent")
		}
		parent, ok := updates[*node.ParentID]
		if !ok {
			return nil, enrichmentValidation("missing enrichment parent")
		}
		submittedParent, name := "", update.Path
		if at := strings.LastIndexByte(update.Path, '/'); at >= 0 {
			submittedParent, name = update.Path[:at], update.Path[at+1:]
		}
		if submittedParent != parent.Path {
			return nil, enrichmentValidation("enrichment cannot reparent nodes")
		}
		markdown := node.Kind == "file" && strings.HasSuffix(node.Name, ".md")
		if markdown != (update.UploadID != nil) {
			return nil, enrichmentValidation("enrichment rewrites exactly the Markdown files")
		}
		if node.Name == "README.md" && (name != "README.md" || update.UploadID == nil) {
			return nil, enrichmentValidation("README must be rewritten")
		}
		if node.Kind == "file" && path.Ext(node.Name) != path.Ext(name) {
			return nil, enrichmentValidation("enrichment cannot change file type")
		}
	}
	return updates, nil
}

func (s *Store) CompleteEnrichment(ctx context.Context, a Generation, manifest EnrichmentManifest) error {
	if err := a.validate(); err != nil {
		return err
	}
	if int64(len(manifest.Nodes)) > s.ProcessingMaxOutputs+1 {
		return uploadState("RESOURCE_LIMIT")
	}
	session, err := s.processingSession(ctx, a, false)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.enrichmentState(ctx, a)
	if err != nil {
		return err
	}
	if p.publication != "parsed" {
		return nil
	}
	nodes, err := session.inventory(ctx, a.FileID, s.ProcessingMaxOutputs)
	if err != nil {
		return err
	}
	updates, err := validateEnrichment(nodes, manifest, a.FileID)
	if err != nil {
		return err
	}
	selected := make(map[uuid.UUID]bool)
	replacements := make(map[uuid.UUID]Upload)
	var bytes, delta int64
	for _, node := range nodes {
		update := updates[node.ID]
		if update.UploadID == nil {
			continue
		}
		id := *update.UploadID
		if node.ID == a.FileID || node.Kind != "file" || selected[id] {
			return enrichmentValidation("invalid enrichment upload selection")
		}
		selected[id] = true
		upload, err := session.loadUpload(ctx, id, uploadAccess{source: &a, stage: "enrichment"})
		if err != nil {
			return err
		}
		var relative string
		var attached *uuid.UUID
		if err = session.tx.QueryRow(ctx, `SELECT relative_path,result_node_id FROM uploads WHERE id=$1`, id).Scan(&relative, &attached); err != nil {
			return databaseError(err)
		}
		if upload.State != "finalized" || attached != nil {
			return uploadState("OUTPUTS_INCOMPLETE")
		}
		if relative != update.Path {
			return enrichmentValidation("enrichment upload path mismatch")
		}
		if upload.SizeBytes > s.ProcessingMaxOutputBytes-bytes {
			return uploadState("RESOURCE_LIMIT")
		}
		bytes += upload.SizeBytes
		delta += upload.SizeBytes - node.SizeBytes
		replacements[node.ID] = upload
	}
	if err = session.usage(ctx, delta); err != nil {
		return err
	}
	ids := make([]uuid.UUID, 0, len(updates))
	for id := range updates {
		ids = append(ids, id)
	}
	// Release all sibling names before applying swaps and overlapping slugs.
	_, err = session.tx.Exec(ctx, `UPDATE nodes SET name='.enrichment-'||id::text WHERE id=ANY($1) AND id!=$2`, ids, a.FileID)
	if err != nil {
		return databaseError(err)
	}
	for _, node := range nodes {
		update := updates[node.ID]
		name := node.Name
		if node.ID != a.FileID {
			name = path.Base(update.Path)
		}
		_, err = session.tx.Exec(ctx, `UPDATE nodes SET name=$2,revision=revision+1,updated_at=now() WHERE id=$1`, node.ID, name)
		if err != nil {
			return databaseError(err)
		}
		if node.Kind == "file" {
			m := update.Metadata
			_, err = session.tx.Exec(ctx, `UPDATE files SET title=$2,description=$3,semantic_type=$4,context=$5,media_type=$6 WHERE node_id=$1`, node.ID, m.Title, m.Description, m.SemanticType, m.Context, node.MediaType)
			if err != nil {
				return databaseError(err)
			}
		}
		if upload, ok := replacements[node.ID]; ok {
			if err = session.queueObject(ctx, node.ID); err != nil {
				return err
			}
			kind := "object"
			if upload.Transport == "inline" {
				kind = "inline"
			}
			_, err = session.tx.Exec(ctx, `UPDATE files SET storage_kind=$2,inline_bytes=$3,object_key=$4 WHERE node_id=$1`, node.ID, kind, upload.content, upload.key)
			if err != nil {
				return databaseError(err)
			}
			_, err = session.tx.Exec(ctx, `UPDATE nodes SET size_bytes=$2 WHERE id=$1`, node.ID, upload.SizeBytes)
			if err != nil {
				return databaseError(err)
			}
			_, err = session.tx.Exec(ctx, `UPDATE uploads SET result_node_id=$2,inline_bytes=NULL,updated_at=now() WHERE id=$1`, upload.ID, node.ID)
			if err != nil {
				return databaseError(err)
			}
		}
	}
	if len(nodes) > 1 {
		var readme *SemanticMetadata
		for _, node := range nodes {
			if node.ParentID != nil && *node.ParentID == a.FileID && node.Name == "README.md" && node.Kind == "file" {
				readme = updates[node.ID].Metadata
				break
			}
		}
		if readme == nil {
			return uploadState("OUTPUTS_INCOMPLETE")
		}
		_, err = session.tx.Exec(ctx, `UPDATE files SET title=$2,description=$3,semantic_type=$4,context=$5 WHERE node_id=$1`, a.FileID, readme.Title, readme.Description, readme.SemanticType, readme.Context)
		if err != nil {
			return databaseError(err)
		}
	}
	if err = session.discardUploads(ctx, a); err != nil {
		return err
	}
	_, err = session.tx.Exec(ctx, `UPDATE files SET publication_status='enriched',processing_error=NULL,processing_updated_at=now() WHERE node_id=$1`, a.FileID)
	if err != nil {
		return databaseError(err)
	}
	return databaseError(session.tx.Commit(ctx))
}

func (s *Store) FailEnrichment(ctx context.Context, a Generation, code string) error {
	if err := a.validate(); err != nil {
		return err
	}
	switch code {
	case "PROCESSING_FAILED", "RESOURCE_LIMIT", "QUOTA_EXCEEDED", "DOCUMENT_INVALID", "DEPENDENCY_UNAVAILABLE":
	default:
		return enrichmentValidation("invalid enrichment failure")
	}
	session, err := s.processingSession(ctx, a, true)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.validateProcessing(ctx, a, "enrichment")
	if err != nil {
		return err
	}
	if p.publication != "parsed" {
		return nil
	}
	if err = session.failProcessing(ctx, a, code); err != nil {
		return err
	}
	return databaseError(session.tx.Commit(ctx))
}
