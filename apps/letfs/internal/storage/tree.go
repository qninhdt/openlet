package storage

import (
	"context"
	"time"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/jackc/pgx/v5"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/types/known/timestamppb"
)

var documentMedia = []string{"application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}

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
		return "pending"
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
	input, err := locatorJSON([]*pb.NodeLocator{r.Root})
	if err != nil {
		return nil, err
	}
	rows, err := s.DB.Query(ctx, resolverCTE+`, tree AS (
 SELECT n.id,n.name,0 AS depth,''::text AS path,r.readonly,n.kind FROM resolved r JOIN nodes n ON n.id=r.id
 UNION ALL SELECT c.id,c.name,t.depth+1,CASE WHEN t.path='' THEN c.name ELSE t.path||'/'||c.name END,t.readonly OR t.kind='file',c.kind FROM tree t JOIN nodes c ON c.parent_id=t.id AND c.storage_id=$2 WHERE t.depth<$4
 ) SELECT id,path,depth,readonly FROM tree ORDER BY path LIMIT $5`, r.WorkspaceId, r.StorageId, input, r.MaxDepth, r.MaxNodes+1)
	if err != nil {
		return nil, err
	}
	ids := []string{}
	readonly := []bool{}
	entries := map[string]*pb.TreeEntry{}
	for rows.Next() {
		var id string
		var ro bool
		entry := new(pb.TreeEntry)
		if err = rows.Scan(&id, &entry.Path, &entry.Depth, &ro); err != nil {
			rows.Close()
			return nil, err
		}
		ids = append(ids, id)
		readonly = append(readonly, ro)
		entries[id] = entry
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return nil, err
	}
	if len(ids) == 0 {
		return nil, notFound()
	}
	out := &pb.ReadTreeResponse{Truncated: len(ids) > int(r.MaxNodes)}
	if out.Truncated {
		ids = ids[:r.MaxNodes]
		readonly = readonly[:r.MaxNodes]
	}
	nodes, err := readNodes(ctx, s.DB, ids, readonly, false)
	if err != nil {
		return nil, err
	}
	for _, v := range nodes {
		entry := entries[v.Node.Id]
		entry.Node = v.Node
		out.Entries = append(out.Entries, entry)
	}
	return out, nil
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
	result, err := s.Graph.CheckBulkPermissions(ctx, &az.CheckBulkPermissionsRequest{Items: items, Consistency: sdk.Consistency(ctx)})
	if err != nil {
		return a, err
	}
	for _, p := range result.Pairs {
		if p.GetError() != nil {
			return a, status.FromProto(p.GetError()).Err()
		}
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
		if v[0].Node == nil || v[1].Node == nil {
			return resolved{}, resolved{}, notFound()
		}
		return v[0], v[1], nil
	}
	// Two distinct storage roots are resolved once each; no per-node resolution.
	source, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, r.Source, false, false)
	if err != nil {
		return resolved{}, resolved{}, err
	}
	parent, err := oneResolved(ctx, tx, r.WorkspaceId, r.DestinationStorageId, r.Parent, false, false)
	return source, parent, err
}
func (s *Server) MoveNode(ctx context.Context, r *pb.TransferNodeRequest) (*pb.Node, error) {
	a, err := s.transferChecks(ctx, r, true)
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
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
 SELECT updated_at,EXISTS(SELECT 1 FROM tree t JOIN files f ON f.node_id=t.id WHERE f.object_key IS NOT NULL) FROM changed WHERE id=$1`, source, storage, parent, name).Scan(&updated, &hasBlob)
	if err == nil && hasBlob && !allowBlob {
		return updated, invalid("destination storage does not allow blob files")
	}
	return updated, err
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
	var raw []byte
	var bytes int64
	var processIDs, processStages []string
	var hasBlob bool
	err = tx.QueryRow(ctx, `WITH RECURSIVE tree AS(SELECT n.* FROM nodes n WHERE id=$1 UNION ALL SELECT n.* FROM tree t JOIN nodes n ON n.parent_id=t.id WHERE t.kind='directory'),
 mapping AS MATERIALIZED(SELECT t.*,gen_random_uuid() AS new_id FROM tree t),
 inserted AS(INSERT INTO nodes(id,storage_id,parent_id,name,kind) SELECT m.new_id,$2,CASE WHEN m.id=$1 THEN $3 ELSE p.new_id END,CASE WHEN m.id=$1 THEN $4 ELSE m.name END,m.kind FROM mapping m LEFT JOIN mapping p ON p.id=m.parent_id RETURNING *),
 payload AS(INSERT INTO files(node_id,version,size_bytes,media_type,text_content,object_key) SELECT m.new_id,1,f.size_bytes,f.media_type,f.text_content,f.object_key FROM mapping m JOIN files f ON f.node_id=m.id JOIN inserted n ON n.id=m.new_id RETURNING *),
 metadata AS(INSERT INTO file_metadata(node_id,title,description,semantic_type,context) SELECT m.new_id,f.title,f.description,f.semantic_type,f.context FROM mapping m JOIN file_metadata f ON f.node_id=m.id JOIN payload p ON p.node_id=m.new_id WHERE m.id=$1 AND $7 RETURNING *),
 processing_new AS(INSERT INTO processing(file_id,stage) SELECT f.node_id,CASE WHEN f.media_type=ANY($8::text[]) THEN 'pending' ELSE 'parsed' END FROM payload f WHERE f.object_key IS NOT NULL AND f.media_type=ANY($5::text[]) AND $6 RETURNING *)
 SELECT `+headerSQL+`,(SELECT coalesce(sum(size_bytes),0) FROM payload),(SELECT coalesce(array_agg(file_id ORDER BY file_id),ARRAY[]::uuid[]) FROM processing_new),(SELECT coalesce(array_agg(stage ORDER BY file_id),ARRAY[]::text[]) FROM processing_new),EXISTS(SELECT 1 FROM payload WHERE object_key IS NOT NULL)
 FROM mapping old JOIN inserted n ON n.id=old.new_id LEFT JOIN payload f ON f.node_id=n.id LEFT JOIN metadata m ON m.node_id=n.id LEFT JOIN processing_new p ON p.file_id=n.id CROSS JOIN LATERAL(SELECT false AS readonly) v WHERE old.id=$1`, source.Node.Id, r.DestinationStorageId, parent.Node.Id, r.Name, ingestMedia, parent.AllowBlob, source.Node.Readonly, documentMedia).Scan(&raw, &bytes, &processIDs, &processStages, &hasBlob)
	if err != nil {
		return nil, err
	}
	if hasBlob && !parent.AllowBlob {
		return nil, invalid("destination storage does not allow blob files")
	}
	if err = protojson.Unmarshal(raw, out); err != nil {
		return nil, err
	}
	if err = s.quota(ctx, tx, r.WorkspaceId, bytes); err != nil {
		return nil, err
	}
	if err = sdk.Finish(ctx, tx, a.String(), "CopyNode", r.RequestId, out); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	for i, id := range processIDs {
		if err = s.dispatch(ctx, id, 1, processStages[i] == "pending"); err != nil {
			return nil, err
		}
	}
	return out, nil
}
