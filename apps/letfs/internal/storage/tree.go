package storage

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/protobuf/types/known/timestamppb"
)

const pdfMedia = "application/pdf"
const docxMedia = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

var documentMedia = []string{
	pdfMedia,
	docxMedia,
	"application/vnd.openxmlformats-officedocument.presentationml.presentation",
	"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

var imageMedia = []string{"image/png", "image/jpeg", "image/webp", "image/gif"}
var ingestMedia = append(append([]string{}, documentMedia...), imageMedia...)

func requiresParse(media string) bool {
	for _, v := range documentMedia {
		if media == v {
			return true
		}
	}
	return false
}

func processingStage(media string) string {
	if requiresParse(media) {
		return "queued"
	}
	return "parsed"
}

func supportedMedia(media string) bool {
	for _, v := range ingestMedia {
		if media == v {
			return true
		}
	}
	return false
}

func (s *Server) ReadTree(ctx context.Context, r *pb.ReadTreeRequest) (*pb.ReadTreeResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	root, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Root, false, false)
	if err != nil {
		return nil, err
	}
	entries := []*pb.TreeEntry{}
	if root.Artifact != nil || (root.Node.Kind == pb.NodeKind_NODE_KIND_FILE && root.BlobID != nil) {
		baseArt := ""
		if root.Artifact != nil {
			baseArt = root.Artifact.Path
		}
		entries = append(entries, &pb.TreeEntry{Node: root.Node, Path: "", Depth: 0})
		if r.MaxDepth > 0 && (root.Artifact == nil || root.Artifact.Kind == "directory") {
			byBlob, err := s.fetchArtifactTrees(ctx, []string{*root.BlobID})
			if err != nil {
				return nil, err
			}
			entries = append(entries, buildArtifactTreeEntries(r.StorageId, root.Node.Id, baseArt, "", 0, r.MaxDepth, byBlob[*root.BlobID])...)
		}
	} else {
		rows, err := s.DB.Query(ctx, `WITH RECURSIVE tree AS (
			SELECT n.id,n.name,0 AS depth,''::text AS path,n.kind,f.blob_id
			FROM nodes n LEFT JOIN files f ON f.node_id=n.id WHERE n.id=$1 AND n.storage_id=$2
			UNION ALL
			SELECT c.id,c.name,t.depth+1,CASE WHEN t.path='' THEN c.name ELSE t.path||'/'||c.name END,c.kind,f.blob_id
			FROM tree t JOIN nodes c ON c.parent_id=t.id AND c.storage_id=$2 LEFT JOIN files f ON f.node_id=c.id
			WHERE t.kind='directory' AND t.depth<$3
		) SELECT id,path,depth,blob_id FROM tree ORDER BY path LIMIT $4`, root.Node.Id, r.StorageId, r.MaxDepth, r.MaxNodes+1)
		if err != nil {
			return nil, err
		}
		type nodeMeta struct {
			id     string
			path   string
			depth  uint32
			blobID *string
		}
		var metas []nodeMeta
		var blobIDs []string
		seenBlobs := map[string]struct{}{}
		for rows.Next() {
			var m nodeMeta
			if err = rows.Scan(&m.id, &m.path, &m.depth, &m.blobID); err != nil {
				rows.Close()
				return nil, err
			}
			metas = append(metas, m)
			if m.blobID != nil && m.depth < r.MaxDepth {
				if _, ok := seenBlobs[*m.blobID]; !ok {
					seenBlobs[*m.blobID] = struct{}{}
					blobIDs = append(blobIDs, *m.blobID)
				}
			}
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return nil, err
		}
		ids := make([]string, len(metas))
		ro := make([]bool, len(metas))
		for i, m := range metas {
			ids[i] = m.id
		}
		nodes, err := readNodes(ctx, s.DB, ids, ro, false)
		if err != nil {
			return nil, err
		}
		byBlob, err := s.fetchArtifactTrees(ctx, blobIDs)
		if err != nil {
			return nil, err
		}
		for i, n := range nodes {
			entries = append(entries, &pb.TreeEntry{Node: n.Node, Path: metas[i].path, Depth: metas[i].depth})
			if metas[i].blobID != nil && metas[i].depth < r.MaxDepth {
				entries = append(entries, buildArtifactTreeEntries(r.StorageId, metas[i].id, "", metas[i].path, metas[i].depth, r.MaxDepth, byBlob[*metas[i].blobID])...)
			}
		}
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].Path < entries[j].Path })
	out := &pb.ReadTreeResponse{Truncated: len(entries) > int(r.MaxNodes)}
	if out.Truncated {
		entries = entries[:r.MaxNodes]
	}
	out.Entries = entries
	return out, nil
}

func (s *Server) fetchArtifactTrees(ctx context.Context, blobIDs []string) (map[string][]artifactScanner, error) {
	out := make(map[string][]artifactScanner, len(blobIDs))
	if len(blobIDs) == 0 {
		return out, nil
	}
	rows, err := s.DB.Query(ctx, `SELECT `+artifactColumns+`,`+artifactPayloadCols(false)+` FROM blob_artifacts a WHERE a.blob_id=ANY($1::uuid[]) ORDER BY a.blob_id,a.path`, blobIDs)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var sc artifactScanner
		if err = rows.Scan(sc.dests(false)...); err != nil {
			return nil, err
		}
		out[sc.a.BlobID] = append(out[sc.a.BlobID], sc)
	}
	return out, rows.Err()
}

func buildArtifactTreeEntries(storageID, baseNodeID, baseArtPath, baseTreePath string, baseDepth, maxDepth uint32, items []artifactScanner) []*pb.TreeEntry {
	dirIDs := map[string]string{baseArtPath: baseNodeID}
	out := make([]*pb.TreeEntry, 0, len(items))
	for _, sc := range items {
		rel := sc.a.Path
		if baseArtPath != "" {
			if !strings.HasPrefix(sc.a.Path, baseArtPath+"/") {
				continue
			}
			rel = strings.TrimPrefix(sc.a.Path, baseArtPath+"/")
		}
		depth := baseDepth + uint32(strings.Count(rel, "/")) + 1
		if depth > maxDepth {
			continue
		}
		if sc.a.Kind == "directory" {
			dirIDs[sc.a.Path] = sc.a.ID
		}
		parentID, ok := dirIDs[sc.a.ParentPath]
		if !ok {
			parentID = baseNodeID
		}
		treePath := rel
		if baseTreePath != "" {
			treePath = baseTreePath + "/" + rel
		}
		out = append(out, &pb.TreeEntry{
			Node:  sc.build(storageID, parentID, false),
			Path:  treePath,
			Depth: depth,
		})
	}
	return out
}

func (s *Server) transferChecks(ctx context.Context, r *pb.TransferNodeRequest, move bool) (sdk.Actor, error) {
	a, err := sdk.ActorFromContext(ctx)
	if err != nil {
		return a, err
	}
	permission := "read"
	if move {
		permission = "write"
	}
	items := []*az.CheckBulkPermissionsRequestItem{{Resource: sdk.Object("storage", r.StorageId), Permission: permission, Subject: sdk.Subject(a)}}
	if r.DestinationStorageId != r.StorageId || !move {
		items = append(items, &az.CheckBulkPermissionsRequestItem{Resource: sdk.Object("storage", r.DestinationStorageId), Permission: "write", Subject: sdk.Subject(a)})
	}
	res, err := s.Graph.CheckBulkPermissions(ctx, &az.CheckBulkPermissionsRequest{Items: items, Consistency: sdk.Consistency(ctx)})
	if err != nil {
		return a, err
	}
	for _, p := range res.Pairs {
		if p.GetItem().Permissionship != az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION {
			return a, permissionDenied()
		}
	}
	return a, nil
}

func transferEndpoints(ctx context.Context, tx pgx.Tx, r *pb.TransferNodeRequest) (resolved, resolved, error) {
	if r.StorageId == r.DestinationStorageId {
		v, err := resolve(ctx, tx, r.WorkspaceId, r.StorageId, []*pb.NodeLocator{r.Source, r.Parent}, false, false)
		if err != nil {
			return resolved{}, resolved{}, err
		}
		if len(v) != 2 || v[0].Node == nil || v[1].Node == nil {
			return resolved{}, resolved{}, notFound()
		}
		return v[0], v[1], nil
	}
	source, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, r.Source, false, false)
	if err != nil {
		return resolved{}, resolved{}, err
	}
	parent, err := oneResolved(ctx, tx, r.WorkspaceId, r.DestinationStorageId, r.Parent, false, false)
	return source, parent, err
}

func (s *Server) checkFileName(node *pb.Node, name string) error {
	if node.File == nil {
		return nil
	}
	kind := sdk.FileBlob
	if node.File.Type == pb.FileType_FILE_TYPE_TEXT {
		kind = sdk.FileText
	}
	_, err := s.fileMedia(name, kind)
	return err
}

func (s *Server) MoveNode(ctx context.Context, r *pb.TransferNodeRequest) (*pb.Node, error) {
	a, err := s.transferChecks(ctx, r, true)
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(pb.Node)
	duplicate, err := sdk.Claim(ctx, tx, a.String(), "MoveNode", r.RequestId, r, out, s.ttl())
	if err != nil {
		return nil, err
	}
	if duplicate {
		return out, tx.Commit(ctx)
	}
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, r.WorkspaceId); err != nil {
		return nil, err
	}
	source, parent, err := transferEndpoints(ctx, tx, r)
	if err != nil {
		return nil, err
	}
	if err = writable(source); err != nil {
		return nil, err
	}
	if err = directory(parent); err != nil {
		return nil, err
	}
	if source.Node.ParentId == nil {
		return nil, invalid("storage root cannot be moved")
	}
	if source.Node.Name != r.Name {
		if err = s.checkFileName(source.Node, r.Name); err != nil {
			return nil, err
		}
	}
	for _, id := range parent.Chain {
		if id == source.Node.Id {
			return nil, invalid("move would create a cycle")
		}
	}
	var updated time.Time
	if r.StorageId == r.DestinationStorageId {
		err = tx.QueryRow(ctx, `UPDATE nodes SET parent_id=$2,name=$3,updated_at=now() WHERE id=$1 RETURNING updated_at`, source.Node.Id, parent.Node.Id, r.Name).Scan(&updated)
	} else {
		updated, err = moveSubtree(ctx, tx, source.Node.Id, r.DestinationStorageId, parent.Node.Id, r.Name, parent.AllowBlob)
	}
	if err != nil {
		return nil, err
	}
	out = source.Node
	out.StorageId = r.DestinationStorageId
	out.ParentId = &parent.Node.Id
	out.Name = r.Name
	out.UpdatedAt = timestamppb.New(updated)
	if err = sdk.Finish(ctx, tx, a.String(), "MoveNode", r.RequestId, out); err != nil {
		return nil, err
	}
	return out, tx.Commit(ctx)
}

func moveSubtree(ctx context.Context, tx pgx.Tx, source, storage, parent, name string, allowBlob bool) (time.Time, error) {
	var updated time.Time
	var hasBlob bool
	err := tx.QueryRow(ctx, `WITH RECURSIVE tree AS (SELECT id FROM nodes WHERE id=$1 UNION ALL SELECT n.id FROM nodes n JOIN tree t ON n.parent_id=t.id),
 changed AS(UPDATE nodes n SET storage_id=$2,parent_id=CASE WHEN n.id=$1 THEN $3 ELSE n.parent_id END,name=CASE WHEN n.id=$1 THEN $4 ELSE n.name END,updated_at=CASE WHEN n.id=$1 THEN now() ELSE n.updated_at END FROM tree t WHERE n.id=t.id RETURNING n.id,n.updated_at)
 SELECT updated_at,EXISTS(SELECT 1 FROM tree t JOIN files f ON f.node_id=t.id WHERE f.blob_id IS NOT NULL) FROM changed WHERE id=$1`, source, storage, parent, name).Scan(&updated, &hasBlob)
	if err != nil {
		return updated, err
	}
	if hasBlob && !allowBlob {
		return updated, invalid("destination storage does not allow blob files")
	}
	return updated, nil
}

func (s *Server) CopyNode(ctx context.Context, r *pb.TransferNodeRequest) (*pb.Node, error) {
	a, err := s.transferChecks(ctx, r, false)
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(pb.Node)
	duplicate, err := sdk.Claim(ctx, tx, a.String(), "CopyNode", r.RequestId, r, out, s.ttl())
	if err != nil {
		return nil, err
	}
	if duplicate {
		return out, tx.Commit(ctx)
	}
	source, parent, err := transferEndpoints(ctx, tx, r)
	if err != nil {
		return nil, err
	}
	if err = directory(parent); err != nil {
		return nil, err
	}
	if err = s.checkFileName(source.Node, r.Name); err != nil {
		return nil, err
	}

	if source.Artifact != nil {
		var copiedKeys []string
		committed := false
		defer func() {
			if !committed {
				for _, key := range copiedKeys {
					_ = s.abortAndDeleteS3Object(context.WithoutCancel(ctx), key, nil)
				}
			}
		}()
		var toProcess []string
		var parseFlags []bool
		out, toProcess, parseFlags, err = s.copyArtifact(ctx, tx, r, source, parent, &copiedKeys)
		if err != nil {
			return nil, err
		}
		if err = sdk.Finish(ctx, tx, a.String(), "CopyNode", r.RequestId, out); err != nil {
			return nil, err
		}
		if err = tx.Commit(ctx); err != nil {
			return nil, err
		}
		committed = true
		for i, blobID := range toProcess {
			if err = s.dispatchBlob(ctx, blobID, parseFlags[i], 0); err != nil {
				return nil, err
			}
		}
		return out, nil
	}

	var sc nodeScanner
	var bytes int64
	var hasBlob bool
	err = tx.QueryRow(ctx, `WITH RECURSIVE tree AS(SELECT n.* FROM nodes n WHERE id=$1 UNION ALL SELECT n.* FROM tree t JOIN nodes n ON n.parent_id=t.id WHERE t.kind='directory'),
 mapping AS(SELECT t.*,gen_random_uuid() AS new_id FROM tree t),
 inserted AS(INSERT INTO nodes(id,storage_id,parent_id,name,kind) SELECT m.new_id,$2,coalesce(parent.new_id,$3),CASE WHEN m.id=$1 THEN $4 ELSE m.name END,m.kind FROM mapping m LEFT JOIN mapping parent ON parent.id=m.parent_id RETURNING *),
 payload AS(INSERT INTO files(node_id,version,blob_id,text_content,size_bytes,media_type) SELECT m.new_id,1,f.blob_id,f.text_content,f.size_bytes,f.media_type FROM mapping m JOIN files f ON f.node_id=m.id JOIN inserted n ON n.id=m.new_id RETURNING *)
 SELECT `+nodeColumns+`,(SELECT coalesce(sum(size_bytes),0) FROM payload),EXISTS(SELECT 1 FROM payload WHERE blob_id IS NOT NULL)
 FROM mapping old JOIN inserted n ON n.id=old.new_id LEFT JOIN payload f ON f.node_id=n.id LEFT JOIN blobs b ON b.id=f.blob_id WHERE old.id=$1`,
		source.Node.Id, r.DestinationStorageId, parent.Node.Id, r.Name).Scan(sc.dests(&bytes, &hasBlob)...)
	if err != nil {
		return nil, err
	}
	if hasBlob && !parent.AllowBlob {
		return nil, invalid("destination storage does not allow blob files")
	}
	out = sc.finish(false)
	if err = s.quota(ctx, tx, r.WorkspaceId, bytes); err != nil {
		return nil, err
	}
	if err = sdk.Finish(ctx, tx, a.String(), "CopyNode", r.RequestId, out); err != nil {
		return nil, err
	}
	return out, tx.Commit(ctx)
}

func (s *Server) copyArtifact(ctx context.Context, tx pgx.Tx, r *pb.TransferNodeRequest, source, parent resolved, copiedKeys *[]string) (*pb.Node, []string, []bool, error) {
	art := source.Artifact
	if art.Kind == "file" {
		return s.copySingleArtifactFile(ctx, tx, r, parent.Node.Id, parent.AllowBlob, r.Name, *art, copiedKeys)
	}
	rootID := uuid.NewString()
	var created time.Time
	if err := tx.QueryRow(ctx, `INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,$3,$4,'directory') RETURNING created_at`,
		rootID, r.DestinationStorageId, parent.Node.Id, r.Name).Scan(&created); err != nil {
		return nil, nil, nil, err
	}
	rows, err := tx.Query(ctx, `SELECT id::text,blob_id::text,path,parent_path,kind,media_type,size_bytes,object_key,text_content FROM blob_artifacts WHERE blob_id=$1 AND path LIKE $2 ESCAPE '\' ORDER BY path`, art.BlobID, prefixPattern(art.Path))
	if err != nil {
		return nil, nil, nil, err
	}
	var children []blobArtifact
	for rows.Next() {
		var c blobArtifact
		if err = rows.Scan(&c.ID, &c.BlobID, &c.Path, &c.ParentPath, &c.Kind, &c.MediaType, &c.SizeBytes, &c.ObjectKey, &c.TextContent); err != nil {
			rows.Close()
			return nil, nil, nil, err
		}
		children = append(children, c)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, nil, nil, err
	}
	dirIDs := map[string]string{art.Path: rootID}
	var toProcess []string
	var parseFlags []bool
	for _, c := range children {
		pid := dirIDs[c.ParentPath]
		if c.Kind == "directory" {
			cid := uuid.NewString()
			if _, err = tx.Exec(ctx, `INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,$3,$4,'directory')`, cid, r.DestinationStorageId, pid, artifactBaseName(c.Path)); err != nil {
				return nil, nil, nil, err
			}
			dirIDs[c.Path] = cid
			continue
		}
		_, blobs, pflags, err := s.copySingleArtifactFile(ctx, tx, r, pid, parent.AllowBlob, artifactBaseName(c.Path), c, copiedKeys)
		if err != nil {
			return nil, nil, nil, err
		}
		toProcess = append(toProcess, blobs...)
		parseFlags = append(parseFlags, pflags...)
	}
	ts := timestamppb.New(created)
	return &pb.Node{
		Id: rootID, StorageId: r.DestinationStorageId, ParentId: &parent.Node.Id, Name: r.Name,
		Kind: pb.NodeKind_NODE_KIND_DIRECTORY, CreatedAt: ts, UpdatedAt: ts,
	}, toProcess, parseFlags, nil
}

func (s *Server) copySingleArtifactFile(ctx context.Context, tx pgx.Tx, r *pb.TransferNodeRequest, parentID string, allowBlob bool, name string, art blobArtifact, copiedKeys *[]string) (*pb.Node, []string, []bool, error) {
	nodeID := uuid.NewString()
	if art.TextContent != nil {
		var text string
		if err := tx.QueryRow(ctx, `SELECT text_content FROM blob_artifacts WHERE id=$1`, art.ID).Scan(&text); err != nil {
			return nil, nil, nil, err
		}
		var created time.Time
		size := int64(len(text))
		if err := s.quota(ctx, tx, r.WorkspaceId, size); err != nil {
			return nil, nil, nil, err
		}
		if err := tx.QueryRow(ctx, `WITH n AS(INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,$3,$4,'file') RETURNING id,created_at),f AS(INSERT INTO files(node_id,version,size_bytes,media_type,text_content) SELECT id,1,$5,$6,$7 FROM n) SELECT created_at FROM n`,
			nodeID, r.DestinationStorageId, parentID, name, size, art.MediaType, text).Scan(&created); err != nil {
			return nil, nil, nil, err
		}
		ts := timestamppb.New(created)
		return &pb.Node{
			Id: nodeID, StorageId: r.DestinationStorageId, ParentId: &parentID, Name: name, Kind: pb.NodeKind_NODE_KIND_FILE,
			CreatedAt: ts, UpdatedAt: ts,
			File: &pb.FileHeader{Type: pb.FileType_FILE_TYPE_TEXT, Version: 1, SizeBytes: size, MediaType: art.MediaType},
		}, nil, nil, nil
	}
	if !allowBlob {
		return nil, nil, nil, invalid("destination storage does not allow blob files")
	}
	if err := s.quota(ctx, tx, r.WorkspaceId, art.SizeBytes); err != nil {
		return nil, nil, nil, err
	}
	var srcKey, checksum string
	if err := tx.QueryRow(ctx, `SELECT object_key,checksum FROM blob_artifacts WHERE id=$1`, art.ID).Scan(&srcKey, &checksum); err != nil {
		return nil, nil, nil, err
	}
	newBlobID := uuid.NewString()
	newKey := fmt.Sprintf("workspaces/%s/blobs/%s/source", r.WorkspaceId, newBlobID)
	var stage *string
	var summary *pb.ProcessingSummary
	if supportedMedia(art.MediaType) {
		st := processingStage(art.MediaType)
		stage = &st
		summary = &pb.ProcessingSummary{Stage: st}
	}
	if _, err := tx.Exec(ctx, `INSERT INTO blobs(id,workspace_id,object_key,size_bytes,media_type,checksum,source_name,processing_stage) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`,
		newBlobID, r.WorkspaceId, newKey, art.SizeBytes, art.MediaType, checksum, name, stage); err != nil {
		return nil, nil, nil, err
	}
	var created time.Time
	if err := tx.QueryRow(ctx, `WITH n AS(INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,$3,$4,'file') RETURNING id,created_at),f AS(INSERT INTO files(node_id,version,blob_id,size_bytes,media_type) SELECT id,1,$5,$6,$7 FROM n) SELECT created_at FROM n`,
		nodeID, r.DestinationStorageId, parentID, name, newBlobID, art.SizeBytes, art.MediaType).Scan(&created); err != nil {
		return nil, nil, nil, err
	}
	if s.S3 != nil {
		copySource := fmt.Sprintf("%s/%s", s.Bucket, srcKey)
		if _, err := s.S3.CopyObject(ctx, &s3.CopyObjectInput{Bucket: &s.Bucket, CopySource: &copySource, Key: &newKey}); err != nil {
			return nil, nil, nil, err
		}
		*copiedKeys = append(*copiedKeys, newKey)
	}
	ts := timestamppb.New(created)
	var toProcess []string
	var parseFlags []bool
	if supportedMedia(art.MediaType) {
		toProcess = append(toProcess, newBlobID)
		parseFlags = append(parseFlags, requiresParse(art.MediaType))
	}
	return &pb.Node{
		Id: nodeID, StorageId: r.DestinationStorageId, ParentId: &parentID, Name: name, Kind: pb.NodeKind_NODE_KIND_FILE,
		CreatedAt: ts, UpdatedAt: ts,
		File: &pb.FileHeader{Type: pb.FileType_FILE_TYPE_BLOB, Version: 1, SizeBytes: art.SizeBytes, MediaType: art.MediaType, Processing: summary},
	}, toProcess, parseFlags, nil
}
