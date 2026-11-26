package chat

import (
	"context"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/chat/v1"
	"google.golang.org/protobuf/types/known/emptypb"
)

func (s *Server) DeleteWorkspaceData(ctx context.Context, r *pb.DeleteWorkspaceDataRequest) (*emptypb.Empty, error) {
	rows, err := s.DB.Query(ctx, `SELECT id::text FROM conversations WHERE workspace_id=$1`, r.WorkspaceId)
	if err != nil {
		return nil, err
	}
	var convIDs []string
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			rows.Close()
			return nil, err
		}
		convIDs = append(convIDs, id)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return nil, err
	}

	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	if len(convIDs) > 0 {
		if _, err = tx.Exec(ctx, `DELETE FROM outbox_events WHERE conversation_id = ANY($1::uuid[])`, convIDs); err != nil {
			return nil, err
		}
	}
	if _, err = tx.Exec(ctx, `DELETE FROM sidebar_layouts WHERE workspace_id=$1`, r.WorkspaceId); err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM conversations WHERE workspace_id=$1`, r.WorkspaceId); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}

	if s.Graph != nil {
		for _, cid := range convIDs {
			_, _ = s.Graph.DeleteRelationships(ctx, &az.DeleteRelationshipsRequest{
				RelationshipFilter: &az.RelationshipFilter{
					ResourceType:       "conversation",
					OptionalResourceId: cid,
				},
			})
		}
	}
	return &emptypb.Empty{}, nil
}

func (s *Server) RemoveAgent(ctx context.Context, r *pb.RemoveAgentRequest) (*emptypb.Empty, error) {
	rows, err := s.DB.Query(ctx,
		`SELECT conversation_id::text FROM conversation_members
		 WHERE workspace_id=$1 AND actor_type='agent' AND actor_id=$2`,
		r.WorkspaceId, r.AgentId,
	)
	if err != nil {
		return nil, err
	}
	var convIDs []string
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			rows.Close()
			return nil, err
		}
		convIDs = append(convIDs, id)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return nil, err
	}

	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx,
		`DELETE FROM conversation_members WHERE workspace_id=$1 AND actor_type='agent' AND actor_id=$2`,
		r.WorkspaceId, r.AgentId,
	); err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx,
		`UPDATE outbox_events SET delivered_at=now()
		 WHERE destination='leta' AND target_id=$1 AND delivered_at IS NULL`,
		r.AgentId,
	); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}

	if s.Graph != nil {
		for _, cid := range convIDs {
			_, _ = s.Graph.DeleteRelationships(ctx, &az.DeleteRelationshipsRequest{
				RelationshipFilter: &az.RelationshipFilter{
					ResourceType:       "conversation",
					OptionalResourceId: cid,
					OptionalSubjectFilter: &az.SubjectFilter{
						SubjectType:       "agent",
						OptionalSubjectId: r.AgentId,
					},
				},
			})
		}
	}
	return &emptypb.Empty{}, nil
}
