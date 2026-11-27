package chat

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/chat/v1"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/structpb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type attachmentJSON struct {
	StorageID string `json:"storage_id"`
	NodeID    string `json:"node_id"`
	Kind      string `json:"kind"`
	Name      string `json:"name"`
	MediaType string `json:"media_type"`
	SizeBytes int64  `json:"size_bytes"`
}

type mentionJSON struct {
	Kind      string  `json:"kind"`
	ID        string  `json:"id"`
	StorageID *string `json:"storage_id,omitempty"`
	NodeID    *string `json:"node_id,omitempty"`
	Label     string  `json:"label"`
}

func marshalAttachments(items []*pb.MessageAttachment) ([]byte, error) {
	arr := make([]attachmentJSON, len(items))
	for i, a := range items {
		arr[i] = attachmentJSON{
			StorageID: a.StorageId,
			NodeID:    a.NodeId,
			Kind:      a.Kind,
			Name:      a.Name,
			MediaType: a.MediaType,
			SizeBytes: a.SizeBytes,
		}
	}
	return json.Marshal(arr)
}

func unmarshalAttachments(raw []byte) []*pb.MessageAttachment {
	var arr []attachmentJSON
	if len(raw) == 0 || json.Unmarshal(raw, &arr) != nil {
		return nil
	}
	out := make([]*pb.MessageAttachment, len(arr))
	for i, a := range arr {
		out[i] = &pb.MessageAttachment{
			StorageId: a.StorageID,
			NodeId:    a.NodeID,
			Kind:      a.Kind,
			Name:      a.Name,
			MediaType: a.MediaType,
			SizeBytes: a.SizeBytes,
		}
	}
	return out
}

func marshalMentions(items []*pb.MessageMention) ([]byte, error) {
	arr := make([]mentionJSON, len(items))
	for i, m := range items {
		arr[i] = mentionJSON{
			Kind:      m.Kind,
			ID:        m.Id,
			StorageID: m.StorageId,
			NodeID:    m.NodeId,
			Label:     m.Label,
		}
	}
	return json.Marshal(arr)
}

func unmarshalMentions(raw []byte) []*pb.MessageMention {
	var arr []mentionJSON
	if len(raw) == 0 || json.Unmarshal(raw, &arr) != nil {
		return nil
	}
	out := make([]*pb.MessageMention, len(arr))
	for i, m := range arr {
		out[i] = &pb.MessageMention{
			Kind:      m.Kind,
			Id:        m.ID,
			StorageId: m.StorageID,
			NodeId:    m.NodeID,
			Label:     m.Label,
		}
	}
	return out
}

func snippetText(content string, hasAttachments bool) string {
	s := strings.Join(strings.Fields(content), " ")
	if s == "" && hasAttachments {
		return "[Attachment]"
	}
	runes := []rune(s)
	if len(runes) > 160 {
		return string(runes[:160]) + "…"
	}
	return s
}

func scanMessage(row pgx.Row) (*pb.Message, error) {
	m := new(pb.Message)
	var attRaw, menRaw, metaRaw []byte
	var createdAt time.Time
	var editedAt, deletedAt *time.Time
	if err := row.Scan(
		&m.Id, &m.ConversationId, &m.Seq, &m.IdempotencyKey,
		&m.SenderType, &m.SenderId, &m.Content, &m.ReplyToId,
		&attRaw, &menRaw, &metaRaw, &createdAt, &editedAt, &deletedAt,
	); err != nil {
		return nil, err
	}
	m.Attachments = unmarshalAttachments(attRaw)
	m.Mentions = unmarshalMentions(menRaw)
	if len(metaRaw) > 0 && string(metaRaw) != "{}" && string(metaRaw) != "null" {
		st := new(structpb.Struct)
		if st.UnmarshalJSON(metaRaw) == nil {
			m.Metadata = st
		}
	}
	m.CreatedAt = timestamppb.New(createdAt)
	if editedAt != nil {
		m.EditedAt = timestamppb.New(*editedAt)
	}
	if deletedAt != nil {
		m.DeletedAt = timestamppb.New(*deletedAt)
		m.Content = ""
		m.Attachments = nil
	}
	return m, nil
}

func messageToPayload(m *pb.Message, workspaceID string) map[string]any {
	attBytes, _ := marshalAttachments(m.Attachments)
	menBytes, _ := marshalMentions(m.Mentions)
	var atts []any
	var mens []any
	_ = json.Unmarshal(attBytes, &atts)
	_ = json.Unmarshal(menBytes, &mens)
	var meta any = map[string]any{}
	if m.Metadata != nil {
		meta = m.Metadata.AsMap()
	}
	out := map[string]any{
		"id":              m.Id,
		"workspace_id":    workspaceID,
		"conversation_id": m.ConversationId,
		"seq":             m.Seq,
		"sender_type":     m.SenderType,
		"sender_id":       m.SenderId,
		"content":         m.Content,
		"attachments":     atts,
		"mentions":        mens,
		"metadata":        meta,
		"created_at":      m.CreatedAt.AsTime().UTC().Format(time.RFC3339Nano),
	}
	if m.IdempotencyKey != nil {
		out["idempotency_key"] = *m.IdempotencyKey
	}
	if m.ReplyToId != nil {
		out["reply_to_id"] = *m.ReplyToId
	}
	if m.EditedAt != nil {
		out["edited_at"] = m.EditedAt.AsTime().UTC().Format(time.RFC3339Nano)
	}
	if m.DeletedAt != nil {
		out["deleted_at"] = m.DeletedAt.AsTime().UTC().Format(time.RFC3339Nano)
	}
	return out
}

func (s *Server) hydrateReactions(ctx context.Context, q queryer, msgs []*pb.Message) error {
	if len(msgs) == 0 {
		return nil
	}
	ids := make([]string, len(msgs))
	byID := make(map[string]*pb.Message, len(msgs))
	for i, m := range msgs {
		ids[i] = m.Id
		byID[m.Id] = m
	}
	rows, err := q.Query(ctx,
		`SELECT message_id::text, actor_type, actor_id::text, emoji, created_at
		 FROM message_reactions
		 WHERE message_id = ANY($1::uuid[])
		 ORDER BY created_at ASC`,
		ids,
	)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var mid string
		var rx pb.MessageReaction
		var created time.Time
		if err = rows.Scan(&mid, &rx.ActorType, &rx.ActorId, &rx.Emoji, &created); err != nil {
			return err
		}
		rx.CreatedAt = timestamppb.New(created)
		if m := byID[mid]; m != nil {
			m.Reactions = append(m.Reactions, &rx)
		}
	}
	return rows.Err()
}

func (s *Server) SendMessage(ctx context.Context, r *pb.SendMessageRequest) (*pb.Message, error) {
	if strings.TrimSpace(r.Content) == "" && len(r.Attachments) == 0 {
		return nil, invalid("message must contain text content or at least one attachment")
	}
	caller, err := s.check(ctx, "conversation", r.ConversationId, "participate")
	if err != nil {
		return nil, err
	}
	attachments, err := s.copyForwardAttachments(ctx, caller, r.WorkspaceId, r.ConversationId, r.Attachments)
	if err != nil {
		return nil, err
	}
	attJSON, err := marshalAttachments(attachments)
	if err != nil {
		return nil, err
	}
	menJSON, err := marshalMentions(r.Mentions)
	if err != nil {
		return nil, err
	}
	metaJSON := []byte("{}")
	if r.Metadata != nil {
		if metaJSON, err = r.Metadata.MarshalJSON(); err != nil {
			return nil, err
		}
	}

	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	var lastSeq int64
	var convType string
	var convTitle string
	var convHandle *string
	err = tx.QueryRow(ctx,
		`SELECT last_seq, type, title, handle FROM conversations WHERE id=$1 AND workspace_id=$2 FOR UPDATE`,
		r.ConversationId, r.WorkspaceId,
	).Scan(&lastSeq, &convType, &convTitle, &convHandle)
	if err == pgx.ErrNoRows {
		return nil, notFound("conversation")
	}
	if err != nil {
		return nil, err
	}

	if r.IdempotencyKey != nil && *r.IdempotencyKey != "" {
		existing, err := scanMessage(tx.QueryRow(ctx,
			`SELECT id::text, conversation_id::text, seq, idempotency_key::text, sender_type, sender_id::text,
			        content, reply_to_id::text, attachments, mentions, metadata, created_at, edited_at, deleted_at
			 FROM messages
			 WHERE conversation_id=$1 AND sender_type=$2 AND sender_id=$3 AND idempotency_key=$4`,
			r.ConversationId, caller.Type, caller.ID, *r.IdempotencyKey,
		))
		if err == nil {
			if err = s.hydrateReactions(ctx, tx, []*pb.Message{existing}); err != nil {
				return nil, err
			}
			return existing, tx.Commit(ctx)
		}
		if err != pgx.ErrNoRows {
			return nil, err
		}
	}

	if r.ReplyToId != nil && *r.ReplyToId != "" {
		var ok bool
		if err = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM messages WHERE id=$1 AND conversation_id=$2)`, *r.ReplyToId, r.ConversationId).Scan(&ok); err != nil {
			return nil, err
		}
		if !ok {
			return nil, invalid("reply_to_id does not belong to this conversation")
		}
	}

	msgID := newUUIDv7()
	newSeq := lastSeq + 1
	msg, err := scanMessage(tx.QueryRow(ctx,
		`INSERT INTO messages(id, conversation_id, seq, idempotency_key, sender_type, sender_id, content, reply_to_id, attachments, mentions, metadata)
		 VALUES($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11::jsonb)
		 RETURNING id::text, conversation_id::text, seq, idempotency_key::text, sender_type, sender_id::text,
		           content, reply_to_id::text, attachments, mentions, metadata, created_at, edited_at, deleted_at`,
		msgID, r.ConversationId, newSeq, r.IdempotencyKey, caller.Type, caller.ID,
		r.Content, r.ReplyToId, string(attJSON), string(menJSON), string(metaJSON),
	))
	if err != nil {
		return nil, err
	}

	previewBytes, _ := json.Marshal(previewJSON{
		ID:             msg.Id,
		Seq:            msg.Seq,
		SenderType:     msg.SenderType,
		SenderID:       msg.SenderId,
		Snippet:        snippetText(msg.Content, len(msg.Attachments) > 0),
		HasAttachments: len(msg.Attachments) > 0,
	})
	if _, err = tx.Exec(ctx,
		`UPDATE conversations SET last_seq=$2, last_msg_at=$3, last_message_preview=$4::jsonb WHERE id=$1`,
		r.ConversationId, newSeq, msg.CreatedAt.AsTime(), string(previewBytes),
	); err != nil {
		return nil, err
	}
	if _, err = tx.Exec(ctx,
		`UPDATE conversation_members SET last_read_seq=GREATEST(last_read_seq, $4)
		 WHERE conversation_id=$1 AND actor_type=$2 AND actor_id=$3`,
		r.ConversationId, caller.Type, caller.ID, newSeq,
	); err != nil {
		return nil, err
	}

	humanChannels, agentIDs, err := s.loadMemberChannels(ctx, tx, r.ConversationId)
	if err != nil {
		return nil, err
	}
	payload := messageToPayload(msg, r.WorkspaceId)
	channels := append(humanChannels, convChannel(r.ConversationId))
	if err = insertOutbox(ctx, tx, "centrifugo", r.ConversationId, &msg.Id, strings.Join(channels, ","), "message.created", payload); err != nil {
		return nil, err
	}
	for _, agentID := range agentIDs {
		if caller.Type == "agent" && caller.ID == agentID {
			continue
		}
		letaPayload := map[string]any{
			"workspace_id":      r.WorkspaceId,
			"conversation_id":   r.ConversationId,
			"conversation_type": convType,
			"title":             convTitle,
			"handle":            convHandle,
			"message_id":        msg.Id,
			"seq":               msg.Seq,
			"sender_type":       msg.SenderType,
			"sender_id":         msg.SenderId,
			"content":           msg.Content,
			"reply_to_id":       msg.ReplyToId,
			"attachments":       json.RawMessage(attJSON),
			"mentions":          json.RawMessage(menJSON),
			"metadata":          json.RawMessage(metaJSON),
		}
		if err = insertOutbox(ctx, tx, "leta", r.ConversationId, &msg.Id, agentID, "agent.message", letaPayload); err != nil {
			return nil, err
		}
	}
	if err = notifyOutbox(ctx, tx); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	return msg, nil
}

func (s *Server) ListMessages(ctx context.Context, r *pb.ListMessagesRequest) (*pb.ListMessagesResponse, error) {
	if _, err := s.check(ctx, "conversation", r.ConversationId, "view"); err != nil {
		return nil, err
	}
	var exists bool
	if err := s.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM conversations WHERE id=$1 AND workspace_id=$2)`, r.ConversationId, r.WorkspaceId).Scan(&exists); err != nil {
		return nil, err
	}
	if !exists {
		return nil, notFound("conversation")
	}

	limit := pageSize(r.Limit)
	modeCount := 0
	if r.BeforeSeq != nil {
		modeCount++
	}
	if r.AfterSeq != nil {
		modeCount++
	}
	if r.AroundSeq != nil || r.AroundMessageId != nil {
		modeCount++
	}
	if modeCount > 1 {
		return nil, invalid("before_seq, after_seq, and around_seq/around_message_id are mutually exclusive")
	}

	const cols = `id::text, conversation_id::text, seq, idempotency_key::text, sender_type, sender_id::text,
		content, reply_to_id::text, attachments, mentions, metadata, created_at, edited_at, deleted_at`
	out := new(pb.ListMessagesResponse)

	if r.Query != "" {
		pattern := "%" + strings.NewReplacer("\\", "\\\\", "%", "\\%", "_", "\\_").Replace(r.Query) + "%"
		rows, err := s.DB.Query(ctx,
			`SELECT `+cols+` FROM messages
			 WHERE conversation_id=$1 AND deleted_at IS NULL AND content ILIKE $2 ESCAPE '\'
			 ORDER BY seq DESC LIMIT $3`,
			r.ConversationId, pattern, limit+1,
		)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		for rows.Next() {
			m, err := scanMessage(rows)
			if err != nil {
				return nil, err
			}
			out.Messages = append(out.Messages, m)
		}
		if err = rows.Err(); err != nil {
			return nil, err
		}
		if len(out.Messages) > limit {
			out.HasBefore = true
			out.Messages = out.Messages[:limit]
		}
		reverseMessages(out.Messages)
		if err = s.hydrateReactions(ctx, s.DB, out.Messages); err != nil {
			return nil, err
		}
		return out, nil
	}

	if r.AroundSeq != nil || r.AroundMessageId != nil {
		var anchorSeq int64
		if r.AroundSeq != nil {
			anchorSeq = *r.AroundSeq
		} else {
			err := s.DB.QueryRow(ctx, `SELECT seq FROM messages WHERE id=$1 AND conversation_id=$2`, *r.AroundMessageId, r.ConversationId).Scan(&anchorSeq)
			if err == pgx.ErrNoRows {
				return nil, notFound("message")
			}
			if err != nil {
				return nil, err
			}
		}
		half := max(1, limit/2)
		rows, err := s.DB.Query(ctx,
			`WITH before_part AS (
				SELECT `+cols+` FROM messages WHERE conversation_id=$1 AND seq < $2 ORDER BY seq DESC LIMIT $3
			),
			after_part AS (
				SELECT `+cols+` FROM messages WHERE conversation_id=$1 AND seq >= $2 ORDER BY seq ASC LIMIT $4
			)
			SELECT * FROM (SELECT * FROM before_part UNION ALL SELECT * FROM after_part) combined
			ORDER BY seq ASC`,
			r.ConversationId, anchorSeq, half+1, half+2,
		)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		var beforeMsgs, afterMsgs []*pb.Message
		for rows.Next() {
			m, err := scanMessage(rows)
			if err != nil {
				return nil, err
			}
			if m.Seq < anchorSeq {
				beforeMsgs = append(beforeMsgs, m)
			} else {
				afterMsgs = append(afterMsgs, m)
			}
		}
		if err = rows.Err(); err != nil {
			return nil, err
		}
		if len(beforeMsgs) > half {
			out.HasBefore = true
			beforeMsgs = beforeMsgs[len(beforeMsgs)-half:]
		}
		if len(afterMsgs) > half+1 {
			out.HasAfter = true
			afterMsgs = afterMsgs[:half+1]
		}
		out.Messages = append(beforeMsgs, afterMsgs...)
		if err = s.hydrateReactions(ctx, s.DB, out.Messages); err != nil {
			return nil, err
		}
		return out, nil
	}

	if r.AfterSeq != nil {
		rows, err := s.DB.Query(ctx,
			`SELECT `+cols+` FROM messages
			 WHERE conversation_id=$1 AND seq > $2
			 ORDER BY seq ASC LIMIT $3`,
			r.ConversationId, *r.AfterSeq, limit+1,
		)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		for rows.Next() {
			m, err := scanMessage(rows)
			if err != nil {
				return nil, err
			}
			out.Messages = append(out.Messages, m)
		}
		if err = rows.Err(); err != nil {
			return nil, err
		}
		if len(out.Messages) > limit {
			out.HasAfter = true
			out.Messages = out.Messages[:limit]
		}
		out.HasBefore = *r.AfterSeq > 0
		if err = s.hydrateReactions(ctx, s.DB, out.Messages); err != nil {
			return nil, err
		}
		return out, nil
	}

	// Default or before_seq mode: fetch latest or older messages, returned in seq ASC order.
	var rows pgx.Rows
	var err error
	if r.BeforeSeq != nil {
		rows, err = s.DB.Query(ctx,
			`SELECT `+cols+` FROM messages
			 WHERE conversation_id=$1 AND seq < $2
			 ORDER BY seq DESC LIMIT $3`,
			r.ConversationId, *r.BeforeSeq, limit+1,
		)
		out.HasAfter = true
	} else {
		rows, err = s.DB.Query(ctx,
			`SELECT `+cols+` FROM messages
			 WHERE conversation_id=$1
			 ORDER BY seq DESC LIMIT $2`,
			r.ConversationId, limit+1,
		)
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		m, err := scanMessage(rows)
		if err != nil {
			return nil, err
		}
		out.Messages = append(out.Messages, m)
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	if len(out.Messages) > limit {
		out.HasBefore = true
		out.Messages = out.Messages[:limit]
	}
	reverseMessages(out.Messages)
	if err = s.hydrateReactions(ctx, s.DB, out.Messages); err != nil {
		return nil, err
	}
	return out, nil
}

func reverseMessages(msgs []*pb.Message) {
	for i, j := 0, len(msgs)-1; i < j; i, j = i+1, j-1 {
		msgs[i], msgs[j] = msgs[j], msgs[i]
	}
}

func (s *Server) EditMessage(ctx context.Context, r *pb.EditMessageRequest) (*pb.Message, error) {
	caller, err := s.check(ctx, "conversation", r.ConversationId, "participate")
	if err != nil {
		return nil, err
	}
	menJSON, err := marshalMentions(r.Mentions)
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	msg, err := scanMessage(tx.QueryRow(ctx,
		`UPDATE messages
		 SET content=$5, mentions=CASE WHEN $6='[]' THEN mentions ELSE $6::jsonb END, edited_at=now()
		 WHERE id=$1 AND conversation_id=$2 AND sender_type=$3 AND sender_id=$4 AND deleted_at IS NULL
		 RETURNING id::text, conversation_id::text, seq, idempotency_key::text, sender_type, sender_id::text,
		           content, reply_to_id::text, attachments, mentions, metadata, created_at, edited_at, deleted_at`,
		r.MessageId, r.ConversationId, caller.Type, caller.ID, r.Content, string(menJSON),
	))
	if err == pgx.ErrNoRows {
		return nil, permissionDenied("message not found or not editable by caller")
	}
	if err != nil {
		return nil, err
	}

	humanChannels, _, err := s.loadMemberChannels(ctx, tx, r.ConversationId)
	if err != nil {
		return nil, err
	}
	channels := append(humanChannels, convChannel(r.ConversationId))
	if err = insertOutbox(ctx, tx, "centrifugo", r.ConversationId, &msg.Id, strings.Join(channels, ","), "message.updated", messageToPayload(msg, r.WorkspaceId)); err != nil {
		return nil, err
	}
	if err = notifyOutbox(ctx, tx); err != nil {
		return nil, err
	}
	if err = s.hydrateReactions(ctx, tx, []*pb.Message{msg}); err != nil {
		return nil, err
	}
	return msg, tx.Commit(ctx)
}

func (s *Server) DeleteMessage(ctx context.Context, r *pb.DeleteMessageRequest) (*emptypb.Empty, error) {
	caller, err := s.check(ctx, "conversation", r.ConversationId, "participate")
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	var seq int64
	err = tx.QueryRow(ctx,
		`UPDATE messages SET deleted_at=now(), content='', attachments='[]'::jsonb
		 WHERE id=$1 AND conversation_id=$2 AND sender_type=$3 AND sender_id=$4 AND deleted_at IS NULL
		 RETURNING seq`,
		r.MessageId, r.ConversationId, caller.Type, caller.ID,
	).Scan(&seq)
	if err == pgx.ErrNoRows {
		return nil, permissionDenied("message not found or not deletable by caller")
	}
	if err != nil {
		return nil, err
	}
	humanChannels, _, err := s.loadMemberChannels(ctx, tx, r.ConversationId)
	if err != nil {
		return nil, err
	}
	channels := append(humanChannels, convChannel(r.ConversationId))
	if err = insertOutbox(ctx, tx, "centrifugo", r.ConversationId, &r.MessageId, strings.Join(channels, ","), "message.deleted", map[string]any{
		"id":              r.MessageId,
		"workspace_id":    r.WorkspaceId,
		"conversation_id": r.ConversationId,
		"seq":             seq,
	}); err != nil {
		return nil, err
	}
	if err = notifyOutbox(ctx, tx); err != nil {
		return nil, err
	}
	return &emptypb.Empty{}, tx.Commit(ctx)
}

func (s *Server) MarkRead(ctx context.Context, r *pb.MarkReadRequest) (*pb.MarkReadResponse, error) {
	caller, err := s.check(ctx, "conversation", r.ConversationId, "participate")
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	var lastRead int64
	err = tx.QueryRow(ctx,
		`UPDATE conversation_members
		 SET last_read_seq = GREATEST(last_read_seq, $4)
		 WHERE conversation_id=$1 AND actor_type=$2 AND actor_id=$3
		 RETURNING last_read_seq`,
		r.ConversationId, caller.Type, caller.ID, r.Seq,
	).Scan(&lastRead)
	if err == pgx.ErrNoRows {
		return nil, notFound("conversation member")
	}
	if err != nil {
		return nil, err
	}

	channels := []string{convChannel(r.ConversationId)}
	if caller.Type == "user" {
		channels = append(channels, userChannel(caller.ID))
	}
	if err = insertOutbox(ctx, tx, "centrifugo", r.ConversationId, nil, strings.Join(channels, ","), "read_receipt", map[string]any{
		"workspace_id":    r.WorkspaceId,
		"conversation_id": r.ConversationId,
		"actor_type":      caller.Type,
		"actor_id":        caller.ID,
		"last_read_seq":   lastRead,
	}); err != nil {
		return nil, err
	}
	if err = notifyOutbox(ctx, tx); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	return &pb.MarkReadResponse{LastReadSeq: lastRead}, nil
}

var _ = fmt.Sprintf
