package storage

import (
	"context"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func (s *Server) TrashNode(ctx context.Context, r *pb.TrashNodeRequest) (*pb.TrashEntry, error) {
	a, err := s.check(ctx, "storage", r.StorageId, "write")
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(pb.TrashEntry)
	duplicate, err := sdk.Claim(ctx, tx, a.String(), "TrashNode", r.RequestId, r, out, s.ttl())
	if err != nil {
		return nil, err
	}
	if duplicate {
		return out, tx.Commit(ctx)
	}
	v, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, r.Target, false, false)
	if err != nil {
		return nil, err
	}
	if err = writable(v); err != nil {
		return nil, err
	}
	if v.Node.ParentId == nil {
		return nil, invalid("storage root cannot be trashed")
	}
	id := uuid.NewString()
	var at time.Time
	err = tx.QueryRow(ctx, `WITH detached AS(UPDATE nodes SET parent_id=NULL,updated_at=now() WHERE id=$1 RETURNING id) INSERT INTO trash_entries(id,node_id,original_parent_id,trashed_by) SELECT $2,id,$3,$4 FROM detached RETURNING trashed_at`,
		v.Node.Id, id, v.Node.ParentId, a.String()).Scan(&at)
	if err != nil {
		return nil, err
	}
	out = &pb.TrashEntry{Id: id, Node: v.Node, OriginalParentId: v.Node.ParentId, TrashedBy: actorRef(a), TrashedAt: timestamppb.New(at)}
	out.Node.ParentId = nil
	out.Node.UpdatedAt = timestamppb.New(at)
	if err = sdk.Finish(ctx, tx, a.String(), "TrashNode", r.RequestId, out); err != nil {
		return nil, err
	}
	return out, tx.Commit(ctx)
}

func parseActor(s string) sdk.Actor {
	if kind, id, ok := strings.Cut(s, ":"); ok {
		return sdk.Actor{Type: kind, ID: id}
	}
	return sdk.Actor{Type: "user", ID: s}
}

func actorRef(a sdk.Actor) *pb.ActorRef {
	if a.Type == "agent" {
		return &pb.ActorRef{Actor: &pb.ActorRef_AgentId{AgentId: a.ID}}
	}
	return &pb.ActorRef{Actor: &pb.ActorRef_UserId{UserId: a.ID}}
}

func (s *Server) ListTrash(ctx context.Context, r *pb.ListTrashRequest) (*pb.ListTrashResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	rows, err := s.DB.Query(ctx, `SELECT `+nodeColumns+`,t.id::text,t.original_parent_id::text,t.trashed_by,t.trashed_at FROM trash_entries t JOIN nodes n ON n.id=t.node_id JOIN storages s ON s.id=n.storage_id `+nodeJoins+` WHERE s.id=$1 AND s.workspace_id=$2 AND ($3::uuid IS NULL OR t.id>$3) ORDER BY t.id LIMIT $4`,
		r.StorageId, r.WorkspaceId, nilString(r.PageToken), pageSize(r.PageSize)+1)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := new(pb.ListTrashResponse)
	for rows.Next() {
		var v pb.TrashEntry
		var sc nodeScanner
		var actor string
		var at time.Time
		if err = rows.Scan(sc.dests(&v.Id, &v.OriginalParentId, &actor, &at)...); err != nil {
			return nil, err
		}
		v.Node = sc.finish(false)
		v.TrashedBy = actorRef(parseActor(actor))
		v.TrashedAt = timestamppb.New(at)
		out.Entries = append(out.Entries, &v)
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	if limit := pageSize(r.PageSize); len(out.Entries) > limit {
		out.Entries = out.Entries[:limit]
		out.NextPageToken = out.Entries[limit-1].Id
	}
	return out, nil
}

func (s *Server) RestoreTrash(ctx context.Context, r *pb.RestoreTrashRequest) (*pb.Node, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "write"); err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	var sc nodeScanner
	var original *string
	err = tx.QueryRow(ctx, `WITH claimed AS(DELETE FROM trash_entries t USING nodes n,storages s WHERE t.id=$1 AND n.id=t.node_id AND s.id=n.storage_id AND s.id=$2 AND s.workspace_id=$3 RETURNING t.node_id,t.original_parent_id) SELECT `+nodeColumns+`,c.original_parent_id::text FROM claimed c JOIN nodes n ON n.id=c.node_id `+nodeJoins,
		r.TrashId, r.StorageId, r.WorkspaceId).Scan(sc.dests(&original)...)
	if err == pgx.ErrNoRows {
		return nil, notFound()
	}
	if err != nil {
		return nil, err
	}
	out := sc.finish(false)
	target := r.Parent
	if target == nil {
		if original == nil {
			return nil, invalid("original parent no longer exists")
		}
		target = &pb.NodeLocator{Locator: &pb.NodeLocator_NodeId{NodeId: *original}}
	}
	parent, err := oneResolved(ctx, tx, r.WorkspaceId, r.StorageId, target, false, false)
	if err != nil {
		return nil, err
	}
	if err = directory(parent); err != nil {
		return nil, err
	}
	name := out.Name
	if r.Name != nil {
		if err = s.checkFileName(out, *r.Name); err != nil {
			return nil, err
		}
		name = *r.Name
	}
	var updated time.Time
	err = tx.QueryRow(ctx, `UPDATE nodes SET parent_id=$2,name=$3,updated_at=now() WHERE id=$1 RETURNING updated_at`, out.Id, parent.Node.Id, name).Scan(&updated)
	if err != nil {
		return nil, err
	}
	out.ParentId = &parent.Node.Id
	out.Name = name
	out.UpdatedAt = timestamppb.New(updated)
	return out, tx.Commit(ctx)
}

func (s *Server) PurgeTrash(ctx context.Context, r *pb.PurgeTrashRequest) (*emptypb.Empty, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "write"); err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	var root string
	err = tx.QueryRow(ctx, `DELETE FROM trash_entries t USING nodes n,storages s WHERE t.id=$1 AND n.id=t.node_id AND s.id=n.storage_id AND s.id=$2 AND s.workspace_id=$3 RETURNING t.node_id`, r.TrashId, r.StorageId, r.WorkspaceId).Scan(&root)
	if err == pgx.ErrNoRows {
		return nil, notFound()
	}
	if err != nil {
		return nil, err
	}
	bytes, blobIDs, err := deleteSubtree(ctx, tx, root)
	if err != nil {
		return nil, err
	}
	if err = s.quota(ctx, tx, r.WorkspaceId, -bytes); err != nil {
		return nil, err
	}
	orphaned, err := markOrphanBlobs(ctx, tx, blobIDs)
	if err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	for _, blobID := range orphaned {
		if err = s.dispatchCleanupBlob(ctx, blobID); err != nil {
			return nil, err
		}
	}
	return &emptypb.Empty{}, nil
}

func deleteSubtree(ctx context.Context, tx pgx.Tx, root string) (int64, []string, error) {
	var bytes int64
	var blobIDs []string
	err := tx.QueryRow(ctx, `WITH RECURSIVE doomed AS(SELECT id FROM nodes WHERE id=$1 UNION ALL SELECT n.id FROM nodes n JOIN doomed d ON n.parent_id=d.id),
		sizes AS MATERIALIZED(SELECT d.id,coalesce(f.size_bytes,0) AS bytes,f.blob_id FROM doomed d LEFT JOIN files f ON f.node_id=d.id),
		deleted AS(DELETE FROM nodes n USING sizes s WHERE n.id=s.id RETURNING s.bytes,s.blob_id)
		SELECT coalesce(sum(bytes),0),coalesce(array_agg(DISTINCT blob_id::text) FILTER(WHERE blob_id IS NOT NULL),'{}') FROM deleted`, root).Scan(&bytes, &blobIDs)
	return bytes, blobIDs, err
}
