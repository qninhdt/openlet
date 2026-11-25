package storage

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgconn"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	statpb "google.golang.org/genproto/googleapis/rpc/status"
	"google.golang.org/grpc/codes"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func (s *Server) Stat(ctx context.Context, r *pb.NodeRequest) (*pb.Node, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	v, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Target, false, false)
	if err != nil {
		return nil, err
	}
	return v.Node, nil
}

func (s *Server) BatchStat(ctx context.Context, r *pb.BatchStatRequest) (*pb.BatchStatResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	nodes, err := resolve(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Targets, false, false)
	if err != nil {
		return nil, err
	}
	out := &pb.BatchStatResponse{Results: make([]*pb.StatResult, len(r.Targets))}
	for i := range r.Targets {
		if nodes[i].Node != nil {
			out.Results[i] = &pb.StatResult{Result: &pb.StatResult_Node{Node: nodes[i].Node}}
		} else {
			out.Results[i] = &pb.StatResult{Result: &pb.StatResult_Error{Error: &statpb.Status{
				Code:    int32(codes.NotFound),
				Message: "node not found",
			}}}
		}
	}
	return out, nil
}

func (s *Server) ListNodes(ctx context.Context, r *pb.ListNodesRequest) (*pb.ListNodesResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	afterName, afterID, err := decodeCursor(r.PageToken)
	if err != nil {
		return nil, err
	}
	target, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Parent, false, false)
	if err != nil {
		return nil, err
	}
	limit := pageSize(r.PageSize)

	if target.Artifact == nil && target.Node.Kind == pb.NodeKind_NODE_KIND_DIRECTORY {
		rows, err := s.DB.Query(ctx, `SELECT `+nodeColumns+` FROM nodes n `+nodeJoins+` WHERE n.parent_id=$1 AND n.storage_id=$2 AND ($3::text IS NULL OR (n.name,n.id)>($3,$4::uuid)) ORDER BY n.name,n.id LIMIT $5`,
			target.Node.Id, r.StorageId, nilString(afterName), nilString(afterID), limit+1)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		out := new(pb.ListNodesResponse)
		for rows.Next() {
			var sc nodeScanner
			if err = rows.Scan(sc.dests()...); err != nil {
				return nil, err
			}
			out.Nodes = append(out.Nodes, sc.finish(false))
		}
		if err = rows.Err(); err != nil {
			return nil, err
		}
		if len(out.Nodes) > limit {
			out.Nodes = out.Nodes[:limit]
			last := out.Nodes[limit-1]
			out.NextPageToken = encodeCursor(last.Name, last.Id)
		}
		return out, nil
	}

	if target.BlobID != nil && (target.Artifact == nil || target.Artifact.Kind == "directory") {
		parentPath := ""
		if target.Artifact != nil {
			parentPath = target.Artifact.Path
		}
		// Fixed parent_path makes path lexicographical order identical to basename order and uses (blob_id, parent_path, path).
		afterPath := ""
		if afterName != "" {
			if parentPath == "" {
				afterPath = afterName
			} else {
				afterPath = parentPath + "/" + afterName
			}
		}
		rows, err := s.DB.Query(ctx, `SELECT `+artifactColumns+`,`+artifactPayloadCols(false)+`
			FROM blob_artifacts a
			WHERE a.blob_id=$1 AND a.parent_path=$2
			  AND ($3::text IS NULL OR (a.path,a.id)>($3,$4::uuid))
			ORDER BY a.path,a.id LIMIT $5`,
			*target.BlobID, parentPath, nilString(afterPath), nilString(afterID), limit+1)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		out := new(pb.ListNodesResponse)
		for rows.Next() {
			var sc artifactScanner
			if err = rows.Scan(sc.dests(false)...); err != nil {
				return nil, err
			}
			out.Nodes = append(out.Nodes, sc.build(r.StorageId, target.Node.Id, false))
		}
		if err = rows.Err(); err != nil {
			return nil, err
		}
		if len(out.Nodes) > limit {
			out.Nodes = out.Nodes[:limit]
			last := out.Nodes[limit-1]
			out.NextPageToken = encodeCursor(last.Name, last.Id)
		}
		return out, nil
	}

	return &pb.ListNodesResponse{}, nil
}

func (s *Server) CreateNode(ctx context.Context, r *pb.CreateNodeRequest) (*pb.Node, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	kind := "directory"
	var text *string
	media := ""
	if t := r.GetText(); t != nil {
		media, err = s.fileMedia(r.Name, sdk.FileText)
		if err != nil {
			return nil, err
		}
		if err = s.validateText(t.Content); err != nil {
			return nil, err
		}
		kind = "file"
		text = &t.Content
	} else if r.GetDirectory() == nil {
		return nil, invalid("node type is required")
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
	var created, updated time.Time
	err = tx.QueryRow(ctx, `WITH inserted AS (INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,$3,$4,$5) RETURNING id,created_at,updated_at),
		payload AS (INSERT INTO files(node_id,version,size_bytes,media_type,text_content) SELECT id,1,octet_length($6::text),$7,$6 FROM inserted WHERE $6::text IS NOT NULL)
		SELECT created_at,updated_at FROM inserted`, id, r.StorageId, parent.Node.Id, r.Name, kind, text, media).Scan(&created, &updated)
	if err != nil {
		return nil, err
	}
	out = &pb.Node{
		Id: id, StorageId: r.StorageId, ParentId: &parent.Node.Id, Name: r.Name,
		CreatedAt: timestamppb.New(created), UpdatedAt: timestamppb.New(updated),
	}
	if text != nil {
		out.Kind = pb.NodeKind_NODE_KIND_FILE
		out.File = &pb.FileHeader{Type: pb.FileType_FILE_TYPE_TEXT, Version: 1, SizeBytes: int64(len(*text)), MediaType: media}
		if err = s.quota(ctx, tx, r.WorkspaceId, out.File.SizeBytes); err != nil {
			return nil, err
		}
	} else {
		out.Kind = pb.NodeKind_NODE_KIND_DIRECTORY
	}
	if err = sdk.Finish(ctx, tx, a.String(), "CreateNode", r.RequestId, out); err != nil {
		return nil, err
	}
	return out, tx.Commit(ctx)
}

func (s *Server) CreateDirectories(ctx context.Context, r *pb.CreateDirectoriesRequest) (*pb.Node, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "write"); err != nil {
		return nil, err
	}
	segments := strings.Split(strings.Trim(r.Path, "/"), "/")
	if len(segments) == 1 && segments[0] == "" {
		segments = nil
	}
	for _, seg := range segments {
		if seg == "" || seg == "." || seg == ".." || strings.ContainsRune(seg, 0) || len(seg) > 255 {
			return nil, invalid("directory path must contain valid names")
		}
	}
	for attempt := range 3 {
		tx, err := s.DB.Begin(ctx)
		if err != nil {
			return nil, err
		}
		base, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, r.Base, false, false)
		if err != nil {
			_ = tx.Rollback(ctx)
			return nil, err
		}
		if err = directory(base); err != nil {
			_ = tx.Rollback(ctx)
			return nil, err
		}
		if len(segments) == 0 {
			return base.Node, tx.Commit(ctx)
		}
		var depth int
		var curID, kind string
		err = tx.QueryRow(ctx, `WITH RECURSIVE walk AS (
			SELECT 0 AS idx,n.id,n.kind FROM nodes n WHERE n.id=$2 AND n.storage_id=$1
			UNION ALL
			SELECT w.idx+1,n.id,n.kind FROM walk w JOIN nodes n ON n.storage_id=$1 AND n.parent_id=w.id AND n.name=($3::text[])[w.idx+1]
			WHERE w.idx<cardinality($3::text[]) AND w.kind='directory'
		) SELECT idx,id::text,kind FROM walk ORDER BY idx DESC LIMIT 1`, r.StorageId, base.Node.Id, segments).Scan(&depth, &curID, &kind)
		if err != nil {
			_ = tx.Rollback(ctx)
			return nil, err
		}
		if kind != "directory" {
			_ = tx.Rollback(ctx)
			return nil, invalid("path conflicts with an existing file")
		}
		var out *pb.Node
		if depth == len(segments) {
			nodes, err := readNodes(ctx, tx, []string{curID}, []bool{false}, false)
			if err != nil || len(nodes) == 0 {
				_ = tx.Rollback(ctx)
				return nil, err
			}
			out = nodes[0].Node
		} else {
			rem := segments[depth:]
			ids := make([]string, len(rem))
			pids := make([]string, len(rem))
			parent := curID
			for i := range rem {
				ids[i] = uuid.NewString()
				pids[i] = parent
				parent = ids[i]
			}
			var created, updated time.Time
			var lastName string
			var lastParent string
			err = tx.QueryRow(ctx, `WITH ins AS (
				INSERT INTO nodes(id,storage_id,parent_id,name,kind)
				SELECT v.id,$1,v.parent_id,v.name,'directory'
				FROM unnest($2::uuid[],$3::uuid[],$4::text[]) WITH ORDINALITY AS v(id,parent_id,name,ord)
				ORDER BY v.ord
				RETURNING id,parent_id,name,created_at,updated_at
			) SELECT parent_id::text,name,created_at,updated_at FROM ins WHERE id=$5`,
				r.StorageId, ids, pids, rem, parent).Scan(&lastParent, &lastName, &created, &updated)
			if err != nil {
				_ = tx.Rollback(ctx)
				var pgErr *pgconn.PgError
				if attempt < 2 && errors.As(err, &pgErr) && pgErr.Code == "23505" {
					continue
				}
				return nil, err
			}
			out = &pb.Node{
				Id: parent, StorageId: r.StorageId, ParentId: &lastParent, Name: lastName,
				Kind: pb.NodeKind_NODE_KIND_DIRECTORY, CreatedAt: timestamppb.New(created), UpdatedAt: timestamppb.New(updated),
			}
		}
		if err = tx.Commit(ctx); err != nil {
			return nil, err
		}
		return out, nil
	}
	return nil, conflict("concurrent directory creation conflict")
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
	var parts []string
	if err = json.Unmarshal(raw, &parts); err != nil || len(parts) != 2 {
		return "", "", invalid("invalid cursor")
	}
	if _, err = uuid.Parse(parts[1]); err != nil {
		return "", "", invalid("invalid cursor")
	}
	return parts[0], parts[1], nil
}
