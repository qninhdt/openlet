package chat

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/jackc/pgx/v5"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/chat/v1"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type previewJSON struct {
	ID             string `json:"id"`
	Seq            int64  `json:"seq"`
	SenderType     string `json:"sender_type"`
	SenderID       string `json:"sender_id"`
	Snippet        string `json:"snippet"`
	HasAttachments bool   `json:"has_attachments"`
}

func scanConversation(row pgx.Row, unreadCount *int64) (*pb.Conversation, error) {
	c := new(pb.Conversation)
	var lastMsgAt *time.Time
	var previewRaw []byte
	var createdAt time.Time
	var err error
	if unreadCount != nil {
		err = row.Scan(
			&c.Id, &c.WorkspaceId, &c.Type, &c.Handle, &c.Title,
			&c.StorageId, &c.StorageReady, &c.LastSeq, &lastMsgAt, &previewRaw,
			&c.CreatedBy, &createdAt, unreadCount,
		)
	} else {
		err = row.Scan(
			&c.Id, &c.WorkspaceId, &c.Type, &c.Handle, &c.Title,
			&c.StorageId, &c.StorageReady, &c.LastSeq, &lastMsgAt, &previewRaw,
			&c.CreatedBy, &createdAt,
		)
	}
	if err != nil {
		return nil, err
	}
	if lastMsgAt != nil {
		c.LastMsgAt = timestamppb.New(*lastMsgAt)
	}
	c.CreatedAt = timestamppb.New(createdAt)
	if len(previewRaw) > 0 && string(previewRaw) != "null" {
		var p previewJSON
		if json.Unmarshal(previewRaw, &p) == nil && p.ID != "" {
			c.LastMessagePreview = &pb.MessagePreview{
				Id:             p.ID,
				Seq:            p.Seq,
				SenderType:     p.SenderType,
				SenderId:       p.SenderID,
				Snippet:        p.Snippet,
				HasAttachments: p.HasAttachments,
			}
		}
	}
	if unreadCount != nil {
		c.UnreadCount = *unreadCount
	}
	return c, nil
}

func (s *Server) hydrateMembers(ctx context.Context, q queryer, convs []*pb.Conversation) error {
	if len(convs) == 0 {
		return nil
	}
	ids := make([]string, len(convs))
	byID := make(map[string]*pb.Conversation, len(convs))
	for i, c := range convs {
		ids[i] = c.Id
		byID[c.Id] = c
	}
	rows, err := q.Query(ctx,
		`SELECT conversation_id::text, actor_type, actor_id::text, role, last_read_seq, muted, joined_at
		 FROM conversation_members
		 WHERE conversation_id = ANY($1::uuid[])
		 ORDER BY joined_at ASC`,
		ids,
	)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var cid string
		var m pb.ConversationMember
		var joined time.Time
		if err = rows.Scan(&cid, &m.ActorType, &m.ActorId, &m.Role, &m.LastReadSeq, &m.Muted, &joined); err != nil {
			return err
		}
		m.JoinedAt = timestamppb.New(joined)
		if conv := byID[cid]; conv != nil {
			conv.Members = append(conv.Members, &m)
		}
	}
	return rows.Err()
}

func convRelationUpdates(workspaceID, convID string, members []struct {
	actor sdk.Actor
	role  string
}) []*az.RelationshipUpdate {
	updates := []*az.RelationshipUpdate{
		sdk.Touch(sdk.Relation("conversation", convID, "workspace", "workspace", workspaceID, "")),
	}
	for _, m := range members {
		rel := "member"
		if m.role == "admin" && m.actor.Type == "user" {
			rel = "admin"
		}
		updates = append(updates, sdk.Touch(sdk.Relation("conversation", convID, rel, m.actor.Type, m.actor.ID, "")))
		if m.actor.Type == "agent" {
			updates = append(updates, sdk.Touch(sdk.Relation("conversation", convID, "agent_member", "agent", m.actor.ID, "")))
		}
	}
	return updates
}

func (s *Server) CreateOrGetDM(ctx context.Context, r *pb.CreateOrGetDMRequest) (*pb.Conversation, error) {
	caller, err := sdk.ActorFromContext(ctx)
	if err != nil {
		return nil, err
	}
	if err = s.checkActorInWorkspace(ctx, r.WorkspaceId, caller); err != nil {
		return nil, err
	}
	target := sdk.Actor{Type: r.Target.Type, ID: r.Target.Id}
	if caller == target {
		return nil, invalid("cannot create a DM with yourself")
	}
	if err = s.verifyTargetAccessible(ctx, caller, r.WorkspaceId, target); err != nil {
		return nil, err
	}
	dmKey := canonicalDMKey(caller, target)

	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	var convID string
	var created bool
	err = tx.QueryRow(ctx, `SELECT id::text FROM conversations WHERE workspace_id=$1 AND dm_key=$2 AND type='dm'`, r.WorkspaceId, dmKey).Scan(&convID)
	if err == pgx.ErrNoRows {
		convID = newUUIDv7()
		var insertedID string
		err = tx.QueryRow(ctx,
			`INSERT INTO conversations(id, workspace_id, type, dm_key, title, created_by)
			 VALUES($1, $2, 'dm', $3, '', $4)
			 ON CONFLICT (workspace_id, dm_key) WHERE type = 'dm'
			 DO UPDATE SET dm_key = conversations.dm_key
			 RETURNING id::text`,
			convID, r.WorkspaceId, dmKey, caller.ID,
		).Scan(&insertedID)
		if err != nil {
			return nil, err
		}
		created = insertedID == convID
		convID = insertedID
		for _, act := range []sdk.Actor{caller, target} {
			_, err = tx.Exec(ctx,
				`INSERT INTO conversation_members(conversation_id, workspace_id, actor_type, actor_id, role)
				 VALUES($1, $2, $3, $4, 'member') ON CONFLICT DO NOTHING`,
				convID, r.WorkspaceId, act.Type, act.ID,
			)
			if err != nil {
				return nil, err
			}
		}
	} else if err != nil {
		return nil, err
	}

	if created {
		var channels []string
		for _, act := range []sdk.Actor{caller, target} {
			if act.Type == "user" {
				channels = append(channels, userChannel(act.ID))
			}
		}
		if len(channels) > 0 {
			if err = insertOutbox(ctx, tx, "centrifugo", convID, nil, strings.Join(channels, ","), "conversation.created", map[string]any{
				"conversation_id": convID,
				"workspace_id":    r.WorkspaceId,
				"type":            "dm",
			}); err != nil {
				return nil, err
			}
			if err = notifyOutbox(ctx, tx); err != nil {
				return nil, err
			}
		}
	}

	var unread int64
	conv, err := scanConversation(tx.QueryRow(ctx,
		`SELECT c.id::text, c.workspace_id::text, c.type, c.handle, c.title,
		        c.storage_id::text, c.storage_ready, c.last_seq, c.last_msg_at,
		        c.last_message_preview, c.created_by::text, c.created_at,
		        GREATEST(0, c.last_seq - coalesce(m.last_read_seq, 0))
		 FROM conversations c
		 LEFT JOIN conversation_members m ON m.conversation_id=c.id AND m.actor_type=$2 AND m.actor_id=$3
		 WHERE c.id=$1`,
		convID, caller.Type, caller.ID,
	), &unread)
	if err != nil {
		return nil, err
	}
	if err = s.hydrateMembers(ctx, tx, []*pb.Conversation{conv}); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}

	// Ensure SpiceDB relationships are present (idempotent Touch).
	if err = s.writeRelations(ctx, convRelationUpdates(r.WorkspaceId, convID, []struct {
		actor sdk.Actor
		role  string
	}{{caller, "member"}, {target, "member"}})...); err != nil {
		return nil, err
	}
	return conv, nil
}

func (s *Server) allocateUniqueGroupHandle(ctx context.Context, tx pgx.Tx, workspaceID, base string) (string, error) {
	rows, err := tx.Query(ctx,
		`SELECT handle FROM conversations
		 WHERE workspace_id=$1 AND type='group' AND (handle=$2 OR handle LIKE $3)`,
		workspaceID, base, base+"-%",
	)
	if err != nil {
		return "", err
	}
	defer rows.Close()
	taken := make(map[string]struct{})
	for rows.Next() {
		var h string
		if err = rows.Scan(&h); err != nil {
			return "", err
		}
		taken[h] = struct{}{}
	}
	if err = rows.Err(); err != nil {
		return "", err
	}
	if _, ok := taken[base]; !ok {
		return base, nil
	}
	for suffix := 2; suffix <= 1000; suffix++ {
		candidate := fmt.Sprintf("%s-%d", base, suffix)
		if _, ok := taken[candidate]; !ok {
			return candidate, nil
		}
	}
	return base + "-" + newUUIDv7()[:8], nil
}

func (s *Server) CreateGroup(ctx context.Context, r *pb.CreateGroupRequest) (*pb.Conversation, error) {
	caller, err := s.check(ctx, "workspace", r.WorkspaceId, "participate")
	if err != nil {
		return nil, err
	}
	if caller.Type != "user" {
		return nil, permissionDenied("only users can create group conversations")
	}
	title := strings.TrimSpace(r.Title)
	if title == "" {
		return nil, invalid("group title is required")
	}

	members := []struct {
		actor sdk.Actor
		role  string
	}{{caller, "admin"}}
	seen := map[sdk.Actor]bool{caller: true}
	var toVerify []sdk.Actor
	for _, m := range r.Members {
		act := sdk.Actor{Type: m.Type, ID: m.Id}
		if seen[act] {
			continue
		}
		seen[act] = true
		toVerify = append(toVerify, act)
		members = append(members, struct {
			actor sdk.Actor
			role  string
		}{act, "member"})
	}
	if len(toVerify) > 0 {
		errs := make([]error, len(toVerify))
		var wg sync.WaitGroup
		sem := make(chan struct{}, 8)
		for i, act := range toVerify {
			wg.Add(1)
			sem <- struct{}{}
			go func(idx int, target sdk.Actor) {
				defer wg.Done()
				defer func() { <-sem }()
				errs[idx] = s.verifyTargetAccessible(ctx, caller, r.WorkspaceId, target)
			}(i, act)
		}
		wg.Wait()
		for _, verr := range errs {
			if verr != nil {
				return nil, verr
			}
		}
	}

	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	baseHandle := slugifyHandle(title)
	if r.Handle != nil && *r.Handle != "" {
		baseHandle = *r.Handle
	}
	handle, err := s.allocateUniqueGroupHandle(ctx, tx, r.WorkspaceId, baseHandle)
	if err != nil {
		return nil, err
	}

	convID := newUUIDv7()
	_, err = tx.Exec(ctx,
		`INSERT INTO conversations(id, workspace_id, type, handle, title, created_by)
		 VALUES($1, $2, 'group', $3, $4, $5)`,
		convID, r.WorkspaceId, handle, title, caller.ID,
	)
	if err != nil {
		return nil, err
	}
	var humanChannels []string
	for _, m := range members {
		_, err = tx.Exec(ctx,
			`INSERT INTO conversation_members(conversation_id, workspace_id, actor_type, actor_id, role)
			 VALUES($1, $2, $3, $4, $5)`,
			convID, r.WorkspaceId, m.actor.Type, m.actor.ID, m.role,
		)
		if err != nil {
			return nil, err
		}
		if m.actor.Type == "user" {
			humanChannels = append(humanChannels, userChannel(m.actor.ID))
		}
	}
	if len(humanChannels) > 0 {
		if err = insertOutbox(ctx, tx, "centrifugo", convID, nil, strings.Join(humanChannels, ","), "conversation.created", map[string]any{
			"conversation_id": convID,
			"workspace_id":    r.WorkspaceId,
			"type":            "group",
			"title":           title,
			"handle":          handle,
		}); err != nil {
			return nil, err
		}
		if err = notifyOutbox(ctx, tx); err != nil {
			return nil, err
		}
	}

	var unread int64
	conv, err := scanConversation(tx.QueryRow(ctx,
		`SELECT id::text, workspace_id::text, type, handle, title, storage_id::text, storage_ready,
		        last_seq, last_msg_at, last_message_preview, created_by::text, created_at, 0::bigint
		 FROM conversations WHERE id=$1`, convID,
	), &unread)
	if err != nil {
		return nil, err
	}
	if err = s.hydrateMembers(ctx, tx, []*pb.Conversation{conv}); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	if err = s.writeRelations(ctx, convRelationUpdates(r.WorkspaceId, convID, members)...); err != nil {
		return nil, err
	}
	return conv, nil
}

func (s *Server) GetConversation(ctx context.Context, r *pb.ConversationRequest) (*pb.Conversation, error) {
	caller, err := s.check(ctx, "conversation", r.ConversationId, "view")
	if err != nil {
		return nil, err
	}
	var unread int64
	conv, err := scanConversation(s.DB.QueryRow(ctx,
		`SELECT c.id::text, c.workspace_id::text, c.type, c.handle, c.title,
		        c.storage_id::text, c.storage_ready, c.last_seq, c.last_msg_at,
		        c.last_message_preview, c.created_by::text, c.created_at,
		        GREATEST(0, c.last_seq - coalesce(m.last_read_seq, c.last_seq))
		 FROM conversations c
		 LEFT JOIN conversation_members m ON m.conversation_id=c.id AND m.actor_type=$3 AND m.actor_id=$4
		 WHERE c.id=$1 AND c.workspace_id=$2`,
		r.ConversationId, r.WorkspaceId, caller.Type, caller.ID,
	), &unread)
	if err == pgx.ErrNoRows {
		return nil, notFound("conversation")
	}
	if err != nil {
		return nil, err
	}
	if err = s.hydrateMembers(ctx, s.DB, []*pb.Conversation{conv}); err != nil {
		return nil, err
	}
	return conv, nil
}

type convCursor struct {
	SortTS time.Time `json:"ts"`
	ID     string    `json:"id"`
}

func encodeConvCursor(c convCursor) string {
	b, _ := json.Marshal(c)
	return base64.RawURLEncoding.EncodeToString(b)
}

func decodeConvCursor(token string) (*convCursor, error) {
	if token == "" {
		return nil, nil
	}
	raw, err := base64.RawURLEncoding.DecodeString(token)
	if err != nil {
		return nil, invalid("invalid page_token")
	}
	var c convCursor
	if err = json.Unmarshal(raw, &c); err != nil || c.ID == "" {
		return nil, invalid("invalid page_token")
	}
	return &c, nil
}

func (s *Server) listActorConversations(ctx context.Context, workspaceID string, actor sdk.Actor, limit int, token string) (*pb.ListConversationsResponse, error) {
	cur, err := decodeConvCursor(token)
	if err != nil {
		return nil, err
	}
	var rows pgx.Rows
	if cur == nil {
		rows, err = s.DB.Query(ctx,
			`SELECT c.id::text, c.workspace_id::text, c.type, c.handle, c.title,
			        c.storage_id::text, c.storage_ready, c.last_seq, c.last_msg_at,
			        c.last_message_preview, c.created_by::text, c.created_at,
			        GREATEST(0, c.last_seq - m.last_read_seq),
			        coalesce(c.last_msg_at, c.created_at) AS sort_ts
			 FROM conversation_members m
			 JOIN conversations c ON c.id = m.conversation_id
			 WHERE m.workspace_id=$1 AND m.actor_type=$2 AND m.actor_id=$3
			 ORDER BY coalesce(c.last_msg_at, c.created_at) DESC, c.id DESC
			 LIMIT $4`,
			workspaceID, actor.Type, actor.ID, limit+1,
		)
	} else {
		rows, err = s.DB.Query(ctx,
			`SELECT c.id::text, c.workspace_id::text, c.type, c.handle, c.title,
			        c.storage_id::text, c.storage_ready, c.last_seq, c.last_msg_at,
			        c.last_message_preview, c.created_by::text, c.created_at,
			        GREATEST(0, c.last_seq - m.last_read_seq),
			        coalesce(c.last_msg_at, c.created_at) AS sort_ts
			 FROM conversation_members m
			 JOIN conversations c ON c.id = m.conversation_id
			 WHERE m.workspace_id=$1 AND m.actor_type=$2 AND m.actor_id=$3
			   AND (coalesce(c.last_msg_at, c.created_at), c.id) < ($4, $5::uuid)
			 ORDER BY coalesce(c.last_msg_at, c.created_at) DESC, c.id DESC
			 LIMIT $6`,
			workspaceID, actor.Type, actor.ID, cur.SortTS, cur.ID, limit+1,
		)
	}
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := new(pb.ListConversationsResponse)
	var sortTimes []time.Time
	for rows.Next() {
		c := new(pb.Conversation)
		var lastMsgAt *time.Time
		var previewRaw []byte
		var createdAt, sortTS time.Time
		var unread int64
		if err = rows.Scan(
			&c.Id, &c.WorkspaceId, &c.Type, &c.Handle, &c.Title,
			&c.StorageId, &c.StorageReady, &c.LastSeq, &lastMsgAt, &previewRaw,
			&c.CreatedBy, &createdAt, &unread, &sortTS,
		); err != nil {
			return nil, err
		}
		if lastMsgAt != nil {
			c.LastMsgAt = timestamppb.New(*lastMsgAt)
		}
		c.CreatedAt = timestamppb.New(createdAt)
		c.UnreadCount = unread
		if len(previewRaw) > 0 && string(previewRaw) != "null" {
			var p previewJSON
			if json.Unmarshal(previewRaw, &p) == nil && p.ID != "" {
				c.LastMessagePreview = &pb.MessagePreview{
					Id: p.ID, Seq: p.Seq, SenderType: p.SenderType, SenderId: p.SenderID,
					Snippet: p.Snippet, HasAttachments: p.HasAttachments,
				}
			}
		}
		out.Conversations = append(out.Conversations, c)
		sortTimes = append(sortTimes, sortTS)
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	if len(out.Conversations) > limit {
		out.Conversations = out.Conversations[:limit]
		out.NextPageToken = encodeConvCursor(convCursor{
			SortTS: sortTimes[limit-1],
			ID:     out.Conversations[limit-1].Id,
		})
	}
	if err = s.hydrateMembers(ctx, s.DB, out.Conversations); err != nil {
		return nil, err
	}
	return out, nil
}

func (s *Server) ListConversations(ctx context.Context, r *pb.ListConversationsRequest) (*pb.ListConversationsResponse, error) {
	caller, err := sdk.ActorFromContext(ctx)
	if err != nil {
		return nil, err
	}
	if err = s.checkActorInWorkspace(ctx, r.WorkspaceId, caller); err != nil {
		return nil, err
	}
	return s.listActorConversations(ctx, r.WorkspaceId, caller, pageSize(r.PageSize), r.PageToken)
}

func (s *Server) ListAgentConversations(ctx context.Context, r *pb.ListAgentConversationsRequest) (*pb.ListConversationsResponse, error) {
	if _, err := s.check(ctx, "agent", r.AgentId, "manage"); err != nil {
		return nil, err
	}
	return s.listActorConversations(ctx, r.WorkspaceId, sdk.Actor{Type: "agent", ID: r.AgentId}, pageSize(r.PageSize), r.PageToken)
}

func (s *Server) UpdateGroup(ctx context.Context, r *pb.UpdateGroupRequest) (*pb.Conversation, error) {
	caller, err := s.check(ctx, "conversation", r.ConversationId, "manage")
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)

	var convType string
	err = tx.QueryRow(ctx, `SELECT type FROM conversations WHERE id=$1 AND workspace_id=$2 FOR UPDATE`, r.ConversationId, r.WorkspaceId).Scan(&convType)
	if err == pgx.ErrNoRows {
		return nil, notFound("conversation")
	}
	if err != nil {
		return nil, err
	}
	if convType != "group" {
		return nil, invalid("only group conversations can be updated")
	}
	var title *string
	if r.Title != nil {
		trimmed := strings.TrimSpace(*r.Title)
		if trimmed == "" {
			return nil, invalid("title cannot be empty")
		}
		title = &trimmed
	}
	if _, err = tx.Exec(ctx,
		`UPDATE conversations SET title=coalesce($3, title), handle=coalesce($4, handle) WHERE id=$1 AND workspace_id=$2`,
		r.ConversationId, r.WorkspaceId, title, r.Handle,
	); err != nil {
		return nil, conflict("group handle already in use or invalid update")
	}

	humanChannels, _, err := s.loadMemberChannels(ctx, tx, r.ConversationId)
	if err != nil {
		return nil, err
	}
	channels := append(humanChannels, convChannel(r.ConversationId))
	if err = insertOutbox(ctx, tx, "centrifugo", r.ConversationId, nil, strings.Join(channels, ","), "conversation.updated", map[string]any{
		"conversation_id": r.ConversationId,
		"workspace_id":    r.WorkspaceId,
		"title":           title,
		"handle":          r.Handle,
	}); err != nil {
		return nil, err
	}
	if err = notifyOutbox(ctx, tx); err != nil {
		return nil, err
	}
	var unread int64
	conv, err := scanConversation(tx.QueryRow(ctx,
		`SELECT c.id::text, c.workspace_id::text, c.type, c.handle, c.title,
		        c.storage_id::text, c.storage_ready, c.last_seq, c.last_msg_at,
		        c.last_message_preview, c.created_by::text, c.created_at,
		        GREATEST(0, c.last_seq - coalesce(m.last_read_seq, 0))
		 FROM conversations c
		 LEFT JOIN conversation_members m ON m.conversation_id=c.id AND m.actor_type=$2 AND m.actor_id=$3
		 WHERE c.id=$1`, r.ConversationId, caller.Type, caller.ID,
	), &unread)
	if err != nil {
		return nil, err
	}
	if err = s.hydrateMembers(ctx, tx, []*pb.Conversation{conv}); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	return conv, nil
}

func (s *Server) AddMembers(ctx context.Context, r *pb.AddMembersRequest) (*pb.Conversation, error) {
	caller, err := s.check(ctx, "conversation", r.ConversationId, "manage")
	if err != nil {
		return nil, err
	}
	var added []struct {
		actor sdk.Actor
		role  string
	}
	for _, m := range r.Members {
		act := sdk.Actor{Type: m.Type, ID: m.Id}
		if err = s.verifyTargetAccessible(ctx, caller, r.WorkspaceId, act); err != nil {
			return nil, err
		}
		added = append(added, struct {
			actor sdk.Actor
			role  string
		}{act, "member"})
	}

	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	var convType string
	err = tx.QueryRow(ctx, `SELECT type FROM conversations WHERE id=$1 AND workspace_id=$2 FOR UPDATE`, r.ConversationId, r.WorkspaceId).Scan(&convType)
	if err == pgx.ErrNoRows {
		return nil, notFound("conversation")
	}
	if err != nil {
		return nil, err
	}
	if convType != "group" {
		return nil, invalid("cannot add members to a DM")
	}
	for _, m := range added {
		if _, err = tx.Exec(ctx,
			`INSERT INTO conversation_members(conversation_id, workspace_id, actor_type, actor_id, role)
			 VALUES($1, $2, $3, $4, 'member') ON CONFLICT DO NOTHING`,
			r.ConversationId, r.WorkspaceId, m.actor.Type, m.actor.ID,
		); err != nil {
			return nil, err
		}
	}
	humanChannels, _, err := s.loadMemberChannels(ctx, tx, r.ConversationId)
	if err != nil {
		return nil, err
	}
	channels := append(humanChannels, convChannel(r.ConversationId))
	if err = insertOutbox(ctx, tx, "centrifugo", r.ConversationId, nil, strings.Join(channels, ","), "conversation.updated", map[string]any{
		"conversation_id": r.ConversationId,
		"workspace_id":    r.WorkspaceId,
	}); err != nil {
		return nil, err
	}
	if err = notifyOutbox(ctx, tx); err != nil {
		return nil, err
	}
	var unread int64
	conv, err := scanConversation(tx.QueryRow(ctx,
		`SELECT c.id::text, c.workspace_id::text, c.type, c.handle, c.title,
		        c.storage_id::text, c.storage_ready, c.last_seq, c.last_msg_at,
		        c.last_message_preview, c.created_by::text, c.created_at,
		        GREATEST(0, c.last_seq - coalesce(m.last_read_seq, 0))
		 FROM conversations c
		 LEFT JOIN conversation_members m ON m.conversation_id=c.id AND m.actor_type=$2 AND m.actor_id=$3
		 WHERE c.id=$1`, r.ConversationId, caller.Type, caller.ID,
	), &unread)
	if err != nil {
		return nil, err
	}
	if err = s.hydrateMembers(ctx, tx, []*pb.Conversation{conv}); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	if err = s.writeRelations(ctx, convRelationUpdates(r.WorkspaceId, r.ConversationId, added)...); err != nil {
		return nil, err
	}
	return conv, nil
}

func (s *Server) removeMemberInternal(ctx context.Context, workspaceID, convID string, target sdk.Actor) error {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	var convType string
	err = tx.QueryRow(ctx, `SELECT type FROM conversations WHERE id=$1 AND workspace_id=$2 FOR UPDATE`, convID, workspaceID).Scan(&convType)
	if err == pgx.ErrNoRows {
		return notFound("conversation")
	}
	if err != nil {
		return err
	}
	if convType != "group" {
		return invalid("cannot remove members from a DM")
	}
	if _, err = tx.Exec(ctx,
		`DELETE FROM conversation_members WHERE conversation_id=$1 AND actor_type=$2 AND actor_id=$3`,
		convID, target.Type, target.ID,
	); err != nil {
		return err
	}
	humanChannels, _, err := s.loadMemberChannels(ctx, tx, convID)
	if err != nil {
		return err
	}
	if target.Type == "user" {
		if err = insertOutbox(ctx, tx, "centrifugo", convID, nil, userChannel(target.ID), "conversation.removed", map[string]any{
			"conversation_id": convID,
			"workspace_id":    workspaceID,
		}); err != nil {
			return err
		}
	}
	channels := append(humanChannels, convChannel(convID))
	if err = insertOutbox(ctx, tx, "centrifugo", convID, nil, strings.Join(channels, ","), "conversation.updated", map[string]any{
		"conversation_id": convID,
		"workspace_id":    workspaceID,
	}); err != nil {
		return err
	}
	if err = notifyOutbox(ctx, tx); err != nil {
		return err
	}
	if err = tx.Commit(ctx); err != nil {
		return err
	}

	updates := []*az.RelationshipUpdate{
		sdk.Delete(sdk.Relation("conversation", convID, "member", target.Type, target.ID, "")),
		sdk.Delete(sdk.Relation("conversation", convID, "admin", target.Type, target.ID, "")),
	}
	if target.Type == "agent" {
		updates = append(updates, sdk.Delete(sdk.Relation("conversation", convID, "agent_member", "agent", target.ID, "")))
	}
	return s.writeRelations(ctx, updates...)
}

func (s *Server) RemoveMember(ctx context.Context, r *pb.RemoveMemberRequest) (*emptypb.Empty, error) {
	if _, err := s.check(ctx, "conversation", r.ConversationId, "manage"); err != nil {
		return nil, err
	}
	if err := s.removeMemberInternal(ctx, r.WorkspaceId, r.ConversationId, sdk.Actor{Type: r.ActorType, ID: r.ActorId}); err != nil {
		return nil, err
	}
	return &emptypb.Empty{}, nil
}

func (s *Server) LeaveConversation(ctx context.Context, r *pb.ConversationRequest) (*emptypb.Empty, error) {
	caller, err := s.check(ctx, "conversation", r.ConversationId, "participate")
	if err != nil {
		return nil, err
	}
	if err = s.removeMemberInternal(ctx, r.WorkspaceId, r.ConversationId, caller); err != nil {
		return nil, err
	}
	return &emptypb.Empty{}, nil
}
