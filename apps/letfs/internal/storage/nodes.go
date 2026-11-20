package storage

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"strings"
	"time"

	"github.com/google/uuid"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func (s *Server) Stat(ctx context.Context, r *pb.NodeRequest) (*pb.Node, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	v, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Target, false, false)
	return v.Node, err
}
func (s *Server) BatchStat(ctx context.Context, r *pb.BatchStatRequest) (*pb.BatchStatResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	nodes, err := resolve(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Targets, false, false)
	if err != nil {
		return nil, err
	}
	out := new(pb.BatchStatResponse)
	for _, v := range nodes {
		if v.Node == nil {
			out.Results = append(out.Results, &pb.StatResult{Result: &pb.StatResult_Error{Error: status.New(codes.NotFound, "node not found within live storage/mount").Proto()}})
		} else {
			out.Results = append(out.Results, &pb.StatResult{Result: &pb.StatResult_Node{Node: v.Node}})
		}
	}
	return out, nil
}
func (s *Server) ListNodes(ctx context.Context, r *pb.ListNodesRequest) (*pb.ListNodesResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	input, err := locatorJSON([]*pb.NodeLocator{r.Parent})
	if err != nil {
		return nil, err
	}
	afterName, afterID, err := decodeCursor(r.PageToken)
	if err != nil {
		return nil, err
	}
	rows, err := s.DB.Query(ctx, resolverCTE+` SELECT r.id,CASE WHEN n.id IS NOT NULL THEN `+headerSQL+` END FROM resolved r JOIN nodes parent ON parent.id=r.id LEFT JOIN LATERAL(SELECT c.* FROM nodes c WHERE c.parent_id=r.id AND c.storage_id=$2 AND ($4::text IS NULL OR (c.name,c.id)>($4,$5::uuid)) ORDER BY c.name,c.id LIMIT $6) n ON true CROSS JOIN LATERAL(SELECT r.readonly OR parent.kind='file' AS readonly) v `+headerJoins+` ORDER BY n.name,n.id`, r.WorkspaceId, r.StorageId, input, nilString(afterName), nilString(afterID), pageSize(r.PageSize)+1)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := new(pb.ListNodesResponse)
	seen := false
	for rows.Next() {
		seen = true
		var parent string
		var raw []byte
		if err = rows.Scan(&parent, &raw); err != nil {
			return nil, err
		}
		if raw != nil {
			n := new(pb.Node)
			if err = protojson.Unmarshal(raw, n); err != nil {
				return nil, err
			}
			out.Nodes = append(out.Nodes, n)
		}
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	if !seen {
		return nil, notFound()
	}
	if len(out.Nodes) > pageSize(r.PageSize) {
		out.Nodes = out.Nodes[:pageSize(r.PageSize)]
		n := out.Nodes[len(out.Nodes)-1]
		out.NextPageToken = encodeCursor(n.Name, n.Id)
	}
	return out, nil
}
func (s *Server) CreateNode(ctx context.Context, r *pb.CreateNodeRequest) (*pb.Node, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	media := ""
	if t := r.GetText(); t != nil {
		media, err = s.fileMedia(r.Name, sdk.FileText)
		if err != nil {
			return nil, err
		}
		if err = s.validateText(t.Content); err != nil {
			return nil, err
		}
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(pb.Node)
	duplicate, err := sdk.Claim(ctx, tx, a.String(), "CreateNode", r.RequestId, r, out, s.ttl())
	if err != nil {
		return nil, err
	}
	if duplicate {
		return out, tx.Commit(ctx)
	}
	parent, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, r.Parent, false, false)
	if err != nil {
		return nil, err
	}
	if err = directory(parent); err != nil {
		return nil, err
	}
	id := uuid.NewString()
	kind := "directory"
	var text *string
	if t := r.GetText(); t != nil {
		kind = "file"
		text = &t.Content
	}
	out.Id = id
	out.StorageId = r.StorageId
	out.Name = r.Name
	out.ParentId = &parent.Node.Id
	out.Kind = pb.NodeKind_NODE_KIND_DIRECTORY
	var created, updated time.Time
	err = tx.QueryRow(ctx, `WITH inserted AS (INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,$3,$4,$5) RETURNING id,created_at,updated_at),payload AS (INSERT INTO files(node_id,version,size_bytes,media_type,text_content) SELECT id,1,octet_length($6::text),$7,$6 FROM inserted WHERE $6::text IS NOT NULL) SELECT created_at,updated_at FROM inserted`, id, r.StorageId, parent.Node.Id, r.Name, kind, text, media).Scan(&created, &updated)
	if err != nil {
		return nil, err
	}
	out.CreatedAt = timestamppb.New(created)
	out.UpdatedAt = timestamppb.New(updated)
	if text != nil {
		out.Kind = pb.NodeKind_NODE_KIND_FILE
		out.File = &pb.FileHeader{Type: pb.FileType_FILE_TYPE_TEXT, Version: 1, SizeBytes: int64(len(*text)), MediaType: media}
		if err = s.quota(ctx, tx, r.WorkspaceId, out.File.SizeBytes); err != nil {
			return nil, err
		}
	}
	if err = sdk.Finish(ctx, tx, a.String(), "CreateNode", r.RequestId, out); err != nil {
		return nil, err
	}
	return out, tx.Commit(ctx)
}
func (s *Server) CreateDirectories(ctx context.Context, r *pb.CreateDirectoriesRequest) (*pb.Node, error) {
	_, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	names := strings.Split(strings.Trim(r.Path, "/"), "/")
	for _, name := range names {
		if name == "" || name == "." || name == ".." || strings.ContainsRune(name, 0) || len(name) > 255 {
			return nil, invalid("directory path must contain valid names")
		}
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(pb.Node)
	base, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, r.Base, false, false)
	if err != nil {
		return nil, err
	}
	if err = directory(base); err != nil {
		return nil, err
	}
	var raw []byte
	err = tx.QueryRow(ctx, `WITH RECURSIVE plan AS (
 SELECT 0 AS step,$1::uuid AS id,NULL::uuid AS parent_id,''::text AS name,'directory'::text AS kind,true AS existing,now() AS created_at,now() AS updated_at
 UNION ALL SELECT p.step+1,coalesce(n.id,gen_random_uuid()),p.id,($3::text[])[p.step+1],coalesce(n.kind,'directory'),n.id IS NOT NULL,coalesce(n.created_at,now()),coalesce(n.updated_at,now()) FROM plan p LEFT JOIN nodes n ON n.parent_id=p.id AND n.storage_id=$2 AND n.name=($3::text[])[p.step+1] WHERE p.step<cardinality($3::text[]) AND p.kind='directory'
 ),inserted AS (INSERT INTO nodes(id,storage_id,parent_id,name,kind) SELECT id,$2,parent_id,name,kind FROM plan WHERE NOT existing RETURNING id)
 SELECT jsonb_build_object('id',id,'storageId',$2::text,'parentId',parent_id,'name',name,'kind','NODE_KIND_DIRECTORY','createdAt',created_at,'updatedAt',updated_at) FROM plan WHERE step=cardinality($3::text[]) AND kind='directory'`, base.Node.Id, r.StorageId, names).Scan(&raw)
	if err != nil {
		return nil, err
	}
	if err = protojson.Unmarshal(raw, out); err != nil {
		return nil, err
	}
	return out, tx.Commit(ctx)
}
func encodeCursor(name, id string) string {
	raw, _ := json.Marshal([]string{name, id})
	return base64.RawURLEncoding.EncodeToString(raw)
}
func decodeCursor(token string) (string, string, error) {
	if token == "" {
		return "", "", nil
	}
	raw, err := base64.RawURLEncoding.DecodeString(token)
	if err != nil {
		return "", "", invalid("invalid cursor")
	}
	var pair []string
	if err = json.Unmarshal(raw, &pair); err != nil || len(pair) != 2 {
		return "", "", invalid("invalid cursor")
	}
	if _, err = uuid.Parse(pair[1]); err != nil {
		return "", "", invalid("invalid cursor")
	}
	return pair[0], pair[1], nil
}
