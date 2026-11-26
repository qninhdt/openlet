package chat

import (
	"context"
	"strings"

	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/chat/v1"
	"google.golang.org/protobuf/types/known/emptypb"
)

func (s *Server) AddReaction(ctx context.Context, r *pb.ReactionRequest) (*emptypb.Empty, error) {
	caller, err := s.check(ctx, "conversation", r.ConversationId, "participate")
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	var ok bool
	if err = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM messages WHERE id=$1 AND conversation_id=$2 AND deleted_at IS NULL)`, r.MessageId, r.ConversationId).Scan(&ok); err != nil {
		return nil, err
	}
	if !ok {
		return nil, notFound("message")
	}

	tag, err := tx.Exec(ctx,
		`INSERT INTO message_reactions(message_id, actor_type, actor_id, emoji)
		 VALUES($1, $2, $3, $4) ON CONFLICT DO NOTHING`,
		r.MessageId, caller.Type, caller.ID, r.Emoji,
	)
	if err != nil {
		return nil, err
	}
	if tag.RowsAffected() == 0 {
		return &emptypb.Empty{}, tx.Commit(ctx)
	}

	humanChannels, agentIDs, err := s.loadMemberChannels(ctx, tx, r.ConversationId)
	if err != nil {
		return nil, err
	}
	payload := map[string]any{
		"workspace_id":    r.WorkspaceId,
		"conversation_id": r.ConversationId,
		"message_id":      r.MessageId,
		"actor_type":      caller.Type,
		"actor_id":        caller.ID,
		"emoji":           r.Emoji,
		"action":          "added",
	}
	channels := append(humanChannels, convChannel(r.ConversationId))
	if err = insertOutbox(ctx, tx, "centrifugo", r.ConversationId, &r.MessageId, strings.Join(channels, ","), "reaction.added", payload); err != nil {
		return nil, err
	}
	for _, agentID := range agentIDs {
		if caller.Type == "agent" && caller.ID == agentID {
			continue
		}
		if err = insertOutbox(ctx, tx, "leta", r.ConversationId, &r.MessageId, agentID, "agent.reaction", payload); err != nil {
			return nil, err
		}
	}
	if err = notifyOutbox(ctx, tx); err != nil {
		return nil, err
	}
	return &emptypb.Empty{}, tx.Commit(ctx)
}

func (s *Server) RemoveReaction(ctx context.Context, r *pb.ReactionRequest) (*emptypb.Empty, error) {
	caller, err := s.check(ctx, "conversation", r.ConversationId, "participate")
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	tag, err := tx.Exec(ctx,
		`DELETE FROM message_reactions WHERE message_id=$1 AND actor_type=$2 AND actor_id=$3 AND emoji=$4`,
		r.MessageId, caller.Type, caller.ID, r.Emoji,
	)
	if err != nil {
		return nil, err
	}
	if tag.RowsAffected() == 0 {
		return &emptypb.Empty{}, tx.Commit(ctx)
	}

	humanChannels, agentIDs, err := s.loadMemberChannels(ctx, tx, r.ConversationId)
	if err != nil {
		return nil, err
	}
	payload := map[string]any{
		"workspace_id":    r.WorkspaceId,
		"conversation_id": r.ConversationId,
		"message_id":      r.MessageId,
		"actor_type":      caller.Type,
		"actor_id":        caller.ID,
		"emoji":           r.Emoji,
		"action":          "removed",
	}
	channels := append(humanChannels, convChannel(r.ConversationId))
	if err = insertOutbox(ctx, tx, "centrifugo", r.ConversationId, &r.MessageId, strings.Join(channels, ","), "reaction.removed", payload); err != nil {
		return nil, err
	}
	for _, agentID := range agentIDs {
		if caller.Type == "agent" && caller.ID == agentID {
			continue
		}
		if err = insertOutbox(ctx, tx, "leta", r.ConversationId, &r.MessageId, agentID, "agent.reaction", payload); err != nil {
			return nil, err
		}
	}
	if err = notifyOutbox(ctx, tx); err != nil {
		return nil, err
	}
	return &emptypb.Empty{}, tx.Commit(ctx)
}
