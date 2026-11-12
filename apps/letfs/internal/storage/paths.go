package storage

import (
	"context"
	"encoding/json"
	"strings"

	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/protobuf/encoding/protojson"
)

// Header deliberately excludes file payloads; reads opt into those separately.
const headerSQL = `jsonb_strip_nulls(jsonb_build_object(
 'id',n.id,'storageId',n.storage_id,'parentId',n.parent_id,'name',n.name,
 'kind',CASE n.kind WHEN 'file' THEN 'NODE_KIND_FILE' ELSE 'NODE_KIND_DIRECTORY' END,
 'createdAt',n.created_at,'updatedAt',n.updated_at,'readonly',v.readonly,
 'file',CASE WHEN f.node_id IS NOT NULL THEN jsonb_build_object(
 'type',CASE WHEN f.text_content IS NOT NULL THEN 'FILE_TYPE_TEXT' ELSE 'FILE_TYPE_BLOB' END,
 'version',f.version::text,'sizeBytes',f.size_bytes::text,'mediaType',f.media_type,
 'metadata',CASE WHEN m.node_id IS NOT NULL THEN jsonb_strip_nulls(jsonb_build_object('title',m.title,'description',m.description,'semanticType',m.semantic_type,'context',m.context)) END,
 'processing',CASE WHEN p.file_id IS NOT NULL THEN jsonb_strip_nulls(jsonb_build_object('stage',p.stage,'errorCode',p.error_code)) END) END))`
const headerJoins = ` LEFT JOIN files f ON f.node_id=n.id LEFT JOIN file_metadata m ON m.node_id=n.id LEFT JOIN processing p ON p.file_id=n.id `
const resolverCTE = `WITH RECURSIVE
 storage AS (SELECT s.* FROM storages s WHERE s.id=$2 AND s.workspace_id=$1),
 inputs AS (SELECT x.ord,x.id,x.path,coalesce(x.root,s.root_node_id) AS root,coalesce(x.cwd,x.root,s.root_node_id) AS cwd,s.root_node_id AS live_root FROM jsonb_to_recordset($3::jsonb) AS x(ord int,id uuid,path text,root uuid,cwd uuid) CROSS JOIN storage s),
 bases AS (SELECT i.ord,n.id,n.parent_id,n.kind,0 AS depth FROM inputs i JOIN nodes n ON n.id=i.cwd AND n.storage_id=$2
 UNION ALL SELECT b.ord,n.id,n.parent_id,n.kind,b.depth+1 FROM bases b JOIN nodes n ON n.id=b.parent_id AND n.storage_id=$2),
 valid_bases AS (SELECT i.ord,bool_or(b.id=i.root) AND bool_or(b.id=i.live_root) AS valid FROM inputs i JOIN bases b ON b.ord=i.ord GROUP BY i.ord),
 walk AS (SELECT i.ord,0 AS step,n.id,n.parent_id,n.kind,string_to_array(trim(both '/' from i.path),'/') AS segments,i.root FROM inputs i JOIN valid_bases vb ON vb.ord=i.ord AND vb.valid JOIN nodes n ON n.id=CASE WHEN left(i.path,1)='/' THEN i.root ELSE i.cwd END AND n.storage_id=$2 WHERE i.path IS NOT NULL
 UNION ALL SELECT w.ord,w.step+1,n.id,n.parent_id,n.kind,w.segments,w.root FROM walk w JOIN nodes n ON n.storage_id=$2 AND (
 (w.segments[w.step+1] IN ('','.') AND n.id=w.id) OR
 (w.segments[w.step+1]='..' AND w.id<>w.root AND n.id=w.parent_id) OR
 (w.segments[w.step+1] NOT IN ('','.','..') AND n.parent_id=w.id AND n.name=w.segments[w.step+1])) WHERE w.step<cardinality(w.segments)),
 targets AS (SELECT ord,id FROM inputs WHERE id IS NOT NULL UNION ALL SELECT ord,id FROM walk WHERE step=cardinality(segments)),
 ancestors AS (SELECT t.ord,n.id,n.parent_id,n.kind,0 AS depth FROM targets t JOIN nodes n ON n.id=t.id AND n.storage_id=$2
 UNION ALL SELECT a.ord,n.id,n.parent_id,n.kind,a.depth+1 FROM ancestors a JOIN nodes n ON n.id=a.parent_id AND n.storage_id=$2),
 valid AS (SELECT a.ord,bool_or(a.id=i.root) AND bool_or(a.id=i.live_root) AS live, bool_or(a.depth>0 AND a.kind='file') AS readonly,array_agg(a.id ORDER BY a.depth) AS chain FROM ancestors a JOIN inputs i ON i.ord=a.ord GROUP BY a.ord),
 resolved AS (SELECT t.ord,t.id,v.readonly,v.chain,i.root FROM targets t JOIN valid v ON v.ord=t.ord AND v.live JOIN inputs i ON i.ord=t.ord)
`

type resolved struct {
	Node       *pb.Node
	Root       string
	Chain      []string
	Text       *string
	ObjectKey  *string
	AllowBlob  bool
	AllowIndex bool
}

func locatorJSON(targets []*pb.NodeLocator) ([]byte, error) {
	items := make([]map[string]any, len(targets))
	for i, t := range targets {
		if t == nil {
			return nil, invalid("locator is required")
		}
		v := map[string]any{"ord": i + 1}
		switch x := t.Locator.(type) {
		case *pb.NodeLocator_NodeId:
			v["id"] = x.NodeId
		case *pb.NodeLocator_Path:
			if strings.ContainsRune(x.Path, 0) {
				return nil, invalid("path contains NUL")
			}
			v["path"] = x.Path
		default:
			return nil, invalid("node ID or path is required")
		}
		if t.RootNodeId != nil {
			v["root"] = *t.RootNodeId
		}
		if t.CwdNodeId != nil {
			v["cwd"] = *t.CwdNodeId
		}
		items[i] = v
	}
	return json.Marshal(items)
}
func resolve(ctx context.Context, q queryer, workspace, storage string, targets []*pb.NodeLocator, payload, lock bool) ([]resolved, error) {
	input, err := locatorJSON(targets)
	if err != nil {
		return nil, err
	}
	columns := "NULL::text,NULL::text"
	if payload {
		columns = "f.text_content,f.object_key"
	}
	lockCTE := ""
	if lock {
		lockCTE = ",locked AS MATERIALIZED (SELECT f.* FROM files f JOIN resolved r ON r.id=f.node_id FOR UPDATE OF f)"
	}
	joins := headerJoins
	if lock {
		joins = strings.Replace(joins, "LEFT JOIN files f", "LEFT JOIN locked f", 1)
	}
	sql := resolverCTE + lockCTE + ` SELECT r.ord,` + headerSQL + `,r.root,r.chain,` + columns + `,s.allow_blob_files,s.allow_indexing FROM resolved r JOIN nodes n ON n.id=r.id CROSS JOIN storage s CROSS JOIN LATERAL(SELECT r.readonly) v ` + joins + ` ORDER BY r.ord`
	rows, err := q.Query(ctx, sql, workspace, storage, input)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]resolved, len(targets))
	for rows.Next() {
		var ord int
		var raw []byte
		var r resolved
		if err = rows.Scan(&ord, &raw, &r.Root, &r.Chain, &r.Text, &r.ObjectKey, &r.AllowBlob, &r.AllowIndex); err != nil {
			return nil, err
		}
		r.Node = new(pb.Node)
		if err = protojson.Unmarshal(raw, r.Node); err != nil {
			return nil, err
		}
		out[ord-1] = r
	}
	return out, rows.Err()
}
func oneResolved(ctx context.Context, q queryer, workspace, storage string, target *pb.NodeLocator, payload, lock bool) (resolved, error) {
	r, err := resolve(ctx, q, workspace, storage, []*pb.NodeLocator{target}, payload, lock)
	if err != nil {
		return resolved{}, err
	}
	if r[0].Node == nil {
		return resolved{}, notFound()
	}
	return r[0], nil
}
