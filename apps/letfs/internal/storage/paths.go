package storage

import (
	"context"
	"encoding/json"
	"path"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/protobuf/types/known/timestamppb"
)

const nodeColumns = `n.id::text,n.storage_id::text,n.parent_id::text,n.name,n.kind,n.created_at,n.updated_at,
	f.node_id IS NOT NULL,f.version,f.size_bytes,f.media_type,f.blob_id::text,f.text_content IS NOT NULL,
	coalesce(b.title,''),coalesce(b.description,''),b.processing_stage,coalesce(b.processing_error_code,'')`

const nodeJoins = ` LEFT JOIN files f ON f.node_id=n.id LEFT JOIN blobs b ON b.id=f.blob_id `

const artifactColumns = `a.id::text,a.blob_id::text,a.path,a.parent_path,a.kind,a.media_type,a.size_bytes,a.title,a.description,a.created_at`

func nonEmptyPtr(v string) *string {
	if v == "" {
		return nil
	}
	return &v
}

func escapeLike(v string) string {
	return strings.NewReplacer("\\", "\\\\", "%", "\\%", "_", "\\_").Replace(v)
}

func literalPattern(query string) string {
	return "%" + escapeLike(query) + "%"
}

func prefixPattern(prefix string) string {
	return escapeLike(prefix) + "/%"
}

type nodeScanner struct {
	node      pb.Node
	parentID  *string
	kind      string
	created   time.Time
	updated   time.Time
	hasFile   bool
	version   *int64
	sizeBytes *int64
	mediaType *string
	blobID    *string
	hasText   *bool
	title     string
	desc      string
	stage     *string
	errCode   string
}

func (s *nodeScanner) dests(extra ...any) []any {
	out := make([]any, 0, 17+len(extra))
	out = append(out,
		&s.node.Id, &s.node.StorageId, &s.parentID, &s.node.Name, &s.kind, &s.created, &s.updated,
		&s.hasFile, &s.version, &s.sizeBytes, &s.mediaType, &s.blobID, &s.hasText,
		&s.title, &s.desc, &s.stage, &s.errCode,
	)
	return append(out, extra...)
}

func (s *nodeScanner) finish(readonly bool) *pb.Node {
	s.node.ParentId = s.parentID
	if s.kind == "file" {
		s.node.Kind = pb.NodeKind_NODE_KIND_FILE
	} else {
		s.node.Kind = pb.NodeKind_NODE_KIND_DIRECTORY
	}
	s.node.CreatedAt = timestamppb.New(s.created)
	s.node.UpdatedAt = timestamppb.New(s.updated)
	s.node.Readonly = readonly
	if s.hasFile {
		ft := pb.FileType_FILE_TYPE_BLOB
		if s.hasText != nil && *s.hasText {
			ft = pb.FileType_FILE_TYPE_TEXT
		}
		var meta *pb.FileMetadata
		if s.blobID != nil && (s.title != "" || s.desc != "") {
			meta = &pb.FileMetadata{Title: nonEmptyPtr(s.title), Description: nonEmptyPtr(s.desc)}
		}
		var proc *pb.ProcessingSummary
		if s.stage != nil {
			proc = &pb.ProcessingSummary{Stage: *s.stage, ErrorCode: nonEmptyPtr(s.errCode)}
		}
		var version, sizeBytes int64
		var mediaType string
		if s.version != nil {
			version = *s.version
		}
		if s.sizeBytes != nil {
			sizeBytes = *s.sizeBytes
		}
		if s.mediaType != nil {
			mediaType = *s.mediaType
		}
		s.node.File = &pb.FileHeader{
			Type:       ft,
			Version:    version,
			SizeBytes:  sizeBytes,
			MediaType:  mediaType,
			Metadata:   meta,
			Processing: proc,
		}
	}
	return &s.node
}

type artifactScanner struct {
	a         blobArtifact
	title     string
	desc      string
	createdAt time.Time
	hasText   bool
}

func (s *artifactScanner) dests(payload bool, extra ...any) []any {
	out := make([]any, 0, 12+len(extra))
	out = append(out, &s.a.ID, &s.a.BlobID, &s.a.Path, &s.a.ParentPath, &s.a.Kind, &s.a.MediaType, &s.a.SizeBytes, &s.title, &s.desc, &s.createdAt)
	if payload {
		out = append(out, &s.a.TextContent, &s.a.ObjectKey)
	} else {
		out = append(out, &s.hasText)
	}
	return append(out, extra...)
}

func (s *artifactScanner) build(storageID, parentID string, payload bool) *pb.Node {
	if !payload && s.a.Kind == "file" {
		empty := ""
		if s.hasText {
			s.a.TextContent = &empty
		} else {
			s.a.ObjectKey = &empty
		}
	}
	return buildArtifactNode(storageID, parentID, s.a, s.title, s.desc, s.createdAt)
}

const resolverCTE = `WITH RECURSIVE
 storage AS (SELECT s.* FROM storages s WHERE s.id=$2 AND s.workspace_id=$1),
 inputs AS (SELECT x.ord,x.id,x.path,coalesce(x.root,s.root_node_id) AS root,coalesce(x.cwd,x.root,s.root_node_id) AS cwd,s.root_node_id AS live_root FROM jsonb_to_recordset($3::jsonb) AS x(ord int,id uuid,path text,root uuid,cwd uuid) CROSS JOIN storage s),
 bases AS (SELECT i.ord,n.id,n.parent_id,n.kind,0 AS depth FROM inputs i JOIN nodes n ON n.id=i.cwd AND n.storage_id=$2
 UNION ALL SELECT b.ord,n.id,n.parent_id,n.kind,b.depth+1 FROM bases b JOIN nodes n ON n.id=b.parent_id AND n.storage_id=$2),
 valid_bases AS (SELECT i.ord,bool_or(b.id=i.root) AND bool_or(b.id=i.live_root) AS valid FROM inputs i JOIN bases b ON b.ord=i.ord GROUP BY i.ord),
 walk AS (SELECT i.ord,0 AS step,n.id,n.parent_id,n.kind,coalesce(string_to_array(nullif(trim(both '/' from i.path),''),'/'),'{}'::text[]) AS segments,i.root FROM inputs i JOIN valid_bases vb ON vb.ord=i.ord AND vb.valid JOIN nodes n ON n.id=CASE WHEN left(i.path,1)='/' THEN i.root ELSE i.cwd END AND n.storage_id=$2 WHERE i.path IS NOT NULL
 UNION ALL SELECT w.ord,w.step+1,n.id,n.parent_id,n.kind,w.segments,w.root FROM walk w JOIN nodes n ON n.storage_id=$2 AND (
 (w.segments[w.step+1] IN ('','.') AND n.id=w.id) OR
 (w.segments[w.step+1]='..' AND w.id<>w.root AND n.id=w.parent_id) OR
 (w.segments[w.step+1] NOT IN ('','.','..') AND n.parent_id=w.id AND n.name=w.segments[w.step+1])) WHERE w.step<cardinality(w.segments) AND w.kind='directory'),
 targets AS (SELECT ord,id,''::text AS rest_path FROM inputs WHERE id IS NOT NULL
 UNION ALL SELECT w.ord,w.id,CASE WHEN w.step=cardinality(w.segments) THEN '' ELSE array_to_string(ARRAY(SELECT s FROM unnest(w.segments[w.step+1:]) AS s WHERE s NOT IN ('','.')),'/') END AS rest_path FROM walk w WHERE w.step=cardinality(w.segments) OR (w.kind='file' AND w.step<cardinality(w.segments) AND NOT ('..' = ANY(w.segments[w.step+1:])))),
 ancestors AS (SELECT t.ord,n.id,n.parent_id,n.kind,0 AS depth FROM targets t JOIN nodes n ON n.id=t.id AND n.storage_id=$2
 UNION ALL SELECT a.ord,n.id,n.parent_id,n.kind,a.depth+1 FROM ancestors a JOIN nodes n ON n.id=a.parent_id AND n.storage_id=$2),
 resolved AS (SELECT t.ord,t.id,t.rest_path,i.root,coalesce(array_agg(a.id ORDER BY a.depth DESC),'{}') AS chain,false AS readonly FROM targets t JOIN inputs i ON i.ord=t.ord JOIN ancestors a ON a.ord=t.ord GROUP BY t.ord,t.id,t.rest_path,i.root,i.live_root HAVING bool_or(a.id=i.root) AND bool_or(a.id=i.live_root))`

type blobArtifact struct {
	ID          string
	BlobID      string
	Path        string
	ParentPath  string
	Kind        string
	MediaType   string
	SizeBytes   int64
	ObjectKey   *string
	TextContent *string
}

type resolved struct {
	Node       *pb.Node
	Root       string
	Chain      []string
	BlobID     *string
	Text       *string
	ObjectKey  *string
	Artifact   *blobArtifact
	AllowBlob  bool
	AllowIndex bool
}

func locatorJSON(targets []*pb.NodeLocator) ([]byte, error) {
	items := make([]map[string]any, len(targets))
	for i, t := range targets {
		if t == nil {
			return nil, invalid("locator is required")
		}
		item := map[string]any{"ord": i}
		if t.RootNodeId != nil {
			item["root"] = *t.RootNodeId
		}
		if t.CwdNodeId != nil {
			item["cwd"] = *t.CwdNodeId
		}
		switch v := t.Locator.(type) {
		case *pb.NodeLocator_NodeId:
			item["id"] = v.NodeId
		case *pb.NodeLocator_Path:
			if strings.ContainsRune(v.Path, 0) {
				return nil, invalid("invalid path")
			}
			item["path"] = v.Path
		default:
			return nil, invalid("locator is required")
		}
		items[i] = item
	}
	return json.Marshal(items)
}

func resolve(ctx context.Context, q queryer, workspace, storage string, targets []*pb.NodeLocator, payload, lock bool) ([]resolved, error) {
	if len(targets) == 0 {
		return nil, nil
	}
	input, err := locatorJSON(targets)
	if err != nil {
		return nil, err
	}
	columns := `NULL::text,NULL::text`
	joins := nodeJoins
	lockCTE := ""
	if lock {
		lockCTE = ",locked AS MATERIALIZED (SELECT f.* FROM files f JOIN resolved r ON r.id=f.node_id FOR UPDATE OF f)"
		joins = ` LEFT JOIN locked f ON f.node_id=n.id LEFT JOIN blobs b ON b.id=f.blob_id `
	}
	if payload {
		columns = `f.text_content,b.object_key`
	}
	sql := resolverCTE + lockCTE + ` SELECT ` + nodeColumns + `,r.ord,r.rest_path,r.root,r.chain,r.readonly,` + columns + `,s.allow_blob_files,s.allow_indexing FROM resolved r JOIN nodes n ON n.id=r.id CROSS JOIN storage s ` + joins + ` ORDER BY r.ord`
	rows, err := q.Query(ctx, sql, workspace, storage, input)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]resolved, len(targets))
	restPaths := make([]string, len(targets))
	for rows.Next() {
		var ord int
		var restPath string
		var ro bool
		var sc nodeScanner
		var r resolved
		if err = rows.Scan(sc.dests(&ord, &restPath, &r.Root, &r.Chain, &ro, &r.Text, &r.ObjectKey, &r.AllowBlob, &r.AllowIndex)...); err != nil {
			return nil, err
		}
		r.Node = sc.finish(ro)
		r.BlobID = sc.blobID
		out[ord] = r
		restPaths[ord] = restPath
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	for i, target := range targets {
		artPath := strings.Trim(target.GetArtifactPath(), "/")
		if target.ArtifactPath != nil && *target.ArtifactPath != "" {
			if restPaths[i] != "" || out[i].Node == nil || out[i].Node.Kind != pb.NodeKind_NODE_KIND_FILE || out[i].BlobID == nil {
				out[i] = resolved{}
				continue
			}
			art, ok, err := resolveBlobArtifact(ctx, q, out[i], artPath, payload)
			if err != nil {
				return nil, err
			}
			if !ok {
				out[i] = resolved{}
				continue
			}
			out[i] = art
			continue
		}
		if restPaths[i] != "" && out[i].Node != nil {
			art, ok, err := resolveBlobArtifact(ctx, q, out[i], restPaths[i], payload)
			if err != nil {
				return nil, err
			}
			if ok {
				out[i] = art
			} else {
				out[i] = resolved{}
			}
			continue
		}
		if out[i].Node == nil {
			art, ok, err := resolveVirtualTarget(ctx, q, workspace, storage, target, payload)
			if err != nil {
				return nil, err
			}
			if ok {
				out[i] = art
			}
		}
	}
	return out, nil
}

func oneResolved(ctx context.Context, q queryer, workspace, storage string, target *pb.NodeLocator, payload, lock bool) (resolved, error) {
	r, err := resolve(ctx, q, workspace, storage, []*pb.NodeLocator{target}, payload, lock)
	if err != nil {
		return resolved{}, err
	}
	if len(r) == 0 || r[0].Node == nil {
		return resolved{}, notFound()
	}
	return r[0], nil
}

func cleanArtifactPath(p string) (string, bool) {
	p = strings.TrimSpace(p)
	p = strings.Trim(p, "/")
	if p == "" || strings.ContainsRune(p, 0) {
		return "", false
	}
	cleaned := path.Clean(p)
	if cleaned == "." || cleaned == ".." || strings.HasPrefix(cleaned, "../") || cleaned != p {
		return "", false
	}
	return cleaned, true
}

func artifactParentPath(p string) string {
	idx := strings.LastIndex(p, "/")
	if idx < 0 {
		return ""
	}
	return p[:idx]
}

func artifactBaseName(p string) string {
	idx := strings.LastIndex(p, "/")
	if idx < 0 {
		return p
	}
	return p[idx+1:]
}

func buildArtifactNode(storageID, parentID string, a blobArtifact, title, desc string, created time.Time) *pb.Node {
	ts := timestamppb.New(created)
	node := &pb.Node{
		Id:        a.ID,
		StorageId: storageID,
		ParentId:  &parentID,
		Name:      artifactBaseName(a.Path),
		Kind:      pb.NodeKind_NODE_KIND_DIRECTORY,
		CreatedAt: ts,
		UpdatedAt: ts,
		Readonly:  true,
	}
	if a.Kind == "file" {
		node.Kind = pb.NodeKind_NODE_KIND_FILE
		ft := pb.FileType_FILE_TYPE_BLOB
		if a.TextContent != nil {
			ft = pb.FileType_FILE_TYPE_TEXT
		}
		var meta *pb.FileMetadata
		if title != "" || desc != "" {
			meta = &pb.FileMetadata{Title: nonEmptyPtr(title), Description: nonEmptyPtr(desc)}
		}
		node.File = &pb.FileHeader{
			Type:      ft,
			Version:   1,
			SizeBytes: a.SizeBytes,
			MediaType: a.MediaType,
			Metadata:  meta,
		}
	}
	return node
}

func artifactPayloadCols(payload bool) string {
	if payload {
		return `a.text_content,a.object_key`
	}
	return `a.text_content IS NOT NULL`
}

func resolveBlobArtifact(ctx context.Context, q queryer, parent resolved, relPath string, payload bool) (resolved, bool, error) {
	cleaned, ok := cleanArtifactPath(relPath)
	if !ok || parent.BlobID == nil {
		return resolved{}, false, nil
	}
	var sc artifactScanner
	var parentID string
	err := q.QueryRow(ctx,
		`SELECT `+artifactColumns+`,`+artifactPayloadCols(payload)+`,coalesce(pa.id,$3)
		 FROM blob_artifacts a LEFT JOIN blob_artifacts pa ON pa.blob_id=a.blob_id AND pa.path=a.parent_path AND a.parent_path<>''
		 WHERE a.blob_id=$1 AND a.path=$2`,
		*parent.BlobID, cleaned, parent.Node.Id).Scan(sc.dests(payload, &parentID)...)
	if err == pgx.ErrNoRows {
		return resolved{}, false, nil
	}
	if err != nil {
		return resolved{}, false, err
	}
	node := sc.build(parent.Node.StorageId, parentID, payload)
	blobID := sc.a.BlobID
	out := resolved{
		Node:       node,
		Root:       parent.Root,
		Chain:      parent.Chain,
		BlobID:     &blobID,
		Artifact:   &sc.a,
		AllowBlob:  parent.AllowBlob,
		AllowIndex: parent.AllowIndex,
	}
	if payload {
		out.Text = sc.a.TextContent
		out.ObjectKey = sc.a.ObjectKey
	}
	return out, true, nil
}

func resolveVirtualTarget(ctx context.Context, q queryer, workspace, storage string, target *pb.NodeLocator, payload bool) (resolved, bool, error) {
	if id := target.GetNodeId(); id != "" {
		if target.ArtifactPath != nil && *target.ArtifactPath != "" {
			return resolved{}, false, nil
		}
		return resolveArtifactByID(ctx, q, workspace, storage, id, target.RootNodeId, target.CwdNodeId, payload)
	}
	rawPath := target.GetPath()
	// Normal paths without '..' or virtual cwd already resolved (or definitively missed) in resolverCTE.
	if (target.CwdNodeId == nil || *target.CwdNodeId == "") && !strings.Contains(rawPath, "..") {
		return resolved{}, false, nil
	}
	return walkVirtualPath(ctx, q, workspace, storage, rawPath, target.RootNodeId, target.CwdNodeId, payload)
}

func resolveArtifactByID(ctx context.Context, q queryer, workspace, storage, artID string, rootScope, cwdScope *string, payload bool) (resolved, bool, error) {
	var fileID, root string
	var chain []string
	var sc artifactScanner
	var parentID string
	var allowBlob, allowIndex bool
	sql := `WITH RECURSIVE candidates AS (
		SELECT a.id,a.blob_id,a.path,a.parent_path,a.kind,a.media_type,a.size_bytes,a.title,a.description,a.created_at,a.text_content,a.object_key,
		       f.node_id AS file_id,coalesce($4::uuid,s.root_node_id) AS scope_root,s.root_node_id AS live_root,s.allow_blob_files,s.allow_indexing
		FROM blob_artifacts a
		JOIN files f ON f.blob_id=a.blob_id
		JOIN nodes n ON n.id=f.node_id AND n.storage_id=$2
		JOIN storages s ON s.id=$2 AND s.workspace_id=$1
		WHERE a.id=$3
	),
	chain AS (
		SELECT c.file_id,c.file_id AS id,n.parent_id,0 AS depth FROM candidates c JOIN nodes n ON n.id=c.file_id
		UNION ALL
		SELECT ch.file_id,n.id,n.parent_id,ch.depth+1 FROM chain ch JOIN nodes n ON n.id=ch.parent_id
	),
	live AS (
		SELECT c.*,array_agg(ch.id ORDER BY ch.depth DESC) AS chain_ids
		FROM candidates c
		JOIN chain ch ON ch.file_id=c.file_id
		GROUP BY c.id,c.blob_id,c.path,c.parent_path,c.kind,c.media_type,c.size_bytes,c.title,c.description,c.created_at,c.text_content,c.object_key,c.file_id,c.scope_root,c.live_root,c.allow_blob_files,c.allow_indexing
		HAVING bool_or(ch.id=c.live_root) AND bool_or(ch.id=c.scope_root)
		ORDER BY c.file_id LIMIT 1
	)
	SELECT ` + artifactColumns + `,` + artifactPayloadCols(payload) + `,a.file_id,a.scope_root,a.chain_ids,coalesce(pa.id,a.file_id),a.allow_blob_files,a.allow_indexing
	FROM live a LEFT JOIN blob_artifacts pa ON pa.blob_id=a.blob_id AND pa.path=a.parent_path AND a.parent_path<>''`
	err := q.QueryRow(ctx, sql, workspace, storage, artID, rootScope).Scan(
		sc.dests(payload, &fileID, &root, &chain, &parentID, &allowBlob, &allowIndex)...,
	)
	if err == pgx.ErrNoRows {
		return resolved{}, false, nil
	}
	if err != nil {
		return resolved{}, false, err
	}
	if cwdScope != nil && *cwdScope != "" && *cwdScope != fileID && *cwdScope != root {
		if !containsID(chain, *cwdScope) {
			var cwdPath string
			err = q.QueryRow(ctx, `SELECT path FROM blob_artifacts WHERE id=$1 AND blob_id=$2`, *cwdScope, sc.a.BlobID).Scan(&cwdPath)
			if err != nil {
				return resolved{}, false, nil
			}
			if sc.a.Path != cwdPath && !strings.HasPrefix(sc.a.Path, cwdPath+"/") {
				return resolved{}, false, nil
			}
		}
	}
	node := sc.build(storage, parentID, payload)
	blobID := sc.a.BlobID
	out := resolved{
		Node:       node,
		Root:       root,
		Chain:      chain,
		BlobID:     &blobID,
		Artifact:   &sc.a,
		AllowBlob:  allowBlob,
		AllowIndex: allowIndex,
	}
	if payload {
		out.Text = sc.a.TextContent
		out.ObjectKey = sc.a.ObjectKey
	}
	return out, true, nil
}

type nodeStep struct {
	id       string
	parentID *string
	kind     string
	blobID   *string
	chain    []string
}

func fetchNodeStep(ctx context.Context, q queryer, storage, id, scopeRoot, storageRoot string) (nodeStep, bool, error) {
	var st nodeStep
	var valid bool
	err := q.QueryRow(ctx, `WITH RECURSIVE anc AS (
		SELECT n.id,n.parent_id,n.kind,f.blob_id::text,0 AS depth FROM nodes n LEFT JOIN files f ON f.node_id=n.id WHERE n.id=$2 AND n.storage_id=$1
		UNION ALL
		SELECT n.id,n.parent_id,n.kind,a.blob_id,a.depth+1 FROM anc a JOIN nodes n ON n.id=a.parent_id AND n.storage_id=$1
	)
	SELECT (SELECT id::text FROM anc WHERE depth=0),
	       (SELECT parent_id::text FROM anc WHERE depth=0),
	       (SELECT kind FROM anc WHERE depth=0),
	       (SELECT blob_id FROM anc WHERE depth=0),
	       coalesce(array_agg(id::text ORDER BY depth DESC),'{}'),
	       bool_or(id=$3) AND bool_or(id=$4)
	FROM anc HAVING count(*)>0`, storage, id, scopeRoot, storageRoot).Scan(&st.id, &st.parentID, &st.kind, &st.blobID, &st.chain, &valid)
	if err == pgx.ErrNoRows || !valid {
		return nodeStep{}, false, nil
	}
	if err != nil {
		return nodeStep{}, false, err
	}
	return st, true, nil
}

func walkVirtualPath(ctx context.Context, q queryer, workspace, storage, rawPath string, rootScope, cwdScope *string, payload bool) (resolved, bool, error) {
	var storageRoot string
	var allowBlob, allowIndex bool
	err := q.QueryRow(ctx, `SELECT root_node_id::text,allow_blob_files,allow_indexing FROM storages WHERE id=$1 AND workspace_id=$2`, storage, workspace).Scan(&storageRoot, &allowBlob, &allowIndex)
	if err == pgx.ErrNoRows {
		return resolved{}, false, nil
	}
	if err != nil {
		return resolved{}, false, err
	}
	scopeRoot := storageRoot
	if rootScope != nil && *rootScope != "" {
		scopeRoot = *rootScope
	}

	var cur nodeStep
	var artSegs []string
	inBlob := false

	if strings.HasPrefix(rawPath, "/") || cwdScope == nil || *cwdScope == "" {
		st, ok, err := fetchNodeStep(ctx, q, storage, scopeRoot, scopeRoot, storageRoot)
		if err != nil || !ok {
			return resolved{}, false, err
		}
		cur = st
		if cur.kind == "file" && cur.blobID != nil && hasMoreSegments(strings.Split(strings.Trim(rawPath, "/"), "/")) {
			inBlob = true
		}
	} else {
		st, ok, err := fetchNodeStep(ctx, q, storage, *cwdScope, scopeRoot, storageRoot)
		if err != nil {
			return resolved{}, false, err
		}
		if ok {
			cur = st
			if cur.kind == "file" && cur.blobID != nil {
				inBlob = true
			}
		} else {
			art, ok, err := resolveArtifactByID(ctx, q, workspace, storage, *cwdScope, rootScope, nil, false)
			if err != nil || !ok {
				return resolved{}, false, err
			}
			inBlob = true
			artSegs = strings.Split(art.Artifact.Path, "/")
			st, ok, err = fetchNodeStep(ctx, q, storage, art.Chain[len(art.Chain)-1], scopeRoot, storageRoot)
			if err != nil || !ok {
				return resolved{}, false, err
			}
			cur = st
		}
	}

	segs := strings.Split(strings.Trim(rawPath, "/"), "/")
	for i, seg := range segs {
		if seg == "" || seg == "." {
			continue
		}
		if inBlob {
			if seg == ".." {
				if len(artSegs) > 0 {
					artSegs = artSegs[:len(artSegs)-1]
					continue
				}
				if cur.id == scopeRoot || cur.parentID == nil {
					return resolved{}, false, nil
				}
				parentSt, ok, err := fetchNodeStep(ctx, q, storage, *cur.parentID, scopeRoot, storageRoot)
				if err != nil || !ok {
					return resolved{}, false, err
				}
				cur = parentSt
				inBlob = false
				continue
			}
			artSegs = append(artSegs, seg)
			continue
		}
		if seg == ".." {
			if cur.id == scopeRoot || cur.parentID == nil {
				return resolved{}, false, nil
			}
			parentSt, ok, err := fetchNodeStep(ctx, q, storage, *cur.parentID, scopeRoot, storageRoot)
			if err != nil || !ok {
				return resolved{}, false, err
			}
			cur = parentSt
			continue
		}
		if cur.kind != "directory" {
			return resolved{}, false, nil
		}
		var next nodeStep
		err := q.QueryRow(ctx, `SELECT n.id::text,n.parent_id::text,n.kind,f.blob_id::text FROM nodes n LEFT JOIN files f ON f.node_id=n.id WHERE n.storage_id=$1 AND n.parent_id=$2 AND n.name=$3`,
			storage, cur.id, seg).Scan(&next.id, &next.parentID, &next.kind, &next.blobID)
		if err == pgx.ErrNoRows {
			return resolved{}, false, nil
		}
		if err != nil {
			return resolved{}, false, err
		}
		next.chain = append(append([]string(nil), cur.chain...), next.id)
		cur = next
		if cur.kind == "file" && hasMoreSegments(segs[i+1:]) {
			if cur.blobID == nil {
				return resolved{}, false, nil
			}
			inBlob = true
			artSegs = nil
		}
	}

	baseNodes, err := readNodes(ctx, q, []string{cur.id}, []bool{false}, payload)
	if err != nil || len(baseNodes) == 0 {
		return resolved{}, false, err
	}
	res := baseNodes[0]
	res.Root = scopeRoot
	res.Chain = cur.chain
	res.AllowBlob = allowBlob
	res.AllowIndex = allowIndex
	if inBlob && len(artSegs) > 0 {
		return resolveBlobArtifact(ctx, q, res, strings.Join(artSegs, "/"), payload)
	}
	return res, true, nil
}

func hasMoreSegments(segs []string) bool {
	for _, s := range segs {
		if s != "" && s != "." {
			return true
		}
	}
	return false
}

func containsID(ids []string, target string) bool {
	for _, id := range ids {
		if id == target {
			return true
		}
	}
	return false
}

func readNodes(ctx context.Context, q queryer, ids []string, readonly []bool, payload bool) ([]resolved, error) {
	if len(ids) == 0 {
		return nil, nil
	}
	columns := `NULL::text,NULL::text`
	if payload {
		columns = `f.text_content,b.object_key`
	}
	rows, err := q.Query(ctx, `SELECT `+nodeColumns+`,f.blob_id::text,`+columns+`,v.readonly FROM unnest($1::uuid[],$2::boolean[]) WITH ORDINALITY v(id,readonly,ord) JOIN nodes n ON n.id=v.id `+nodeJoins+` ORDER BY v.ord`, ids, readonly)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]resolved, 0, len(ids))
	for rows.Next() {
		var sc nodeScanner
		var ro bool
		var v resolved
		if err = rows.Scan(sc.dests(&v.BlobID, &v.Text, &v.ObjectKey, &ro)...); err != nil {
			return nil, err
		}
		v.Node = sc.finish(ro)
		out = append(out, v)
	}
	return out, rows.Err()
}
