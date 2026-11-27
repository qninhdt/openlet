package chat

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"math"
	"strings"
	"sync"
	"time"

	letapb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/leta/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type outboxRow struct {
	ID             int64
	Destination    string
	ConversationID string
	MessageID      *string
	TargetID       string
	EventType      string
	Payload        []byte
	Attempts       int
}

func (s *Server) outboxBatchSize() int {
	if s.Settings.Outbox.BatchSize > 0 {
		return s.Settings.Outbox.BatchSize
	}
	return 64
}

func (s *Server) outboxPollInterval() time.Duration {
	if s.Settings.Outbox.PollIntervalSeconds > 0 {
		return time.Duration(s.Settings.Outbox.PollIntervalSeconds) * time.Second
	}
	return 2 * time.Second
}

func (s *Server) outboxMaxBackoff() time.Duration {
	if s.Settings.Outbox.MaxBackoffSeconds > 0 {
		return time.Duration(s.Settings.Outbox.MaxBackoffSeconds) * time.Second
	}
	return 60 * time.Second
}

func (s *Server) outboxRetention() time.Duration {
	if s.Settings.Outbox.RetentionHours > 0 {
		return time.Duration(s.Settings.Outbox.RetentionHours) * time.Hour
	}
	return 24 * time.Hour
}

func (s *Server) RunOutboxWorker(ctx context.Context) {
	wake := make(chan struct{}, 1)
	go s.listenOutboxNotifications(ctx, wake)

	pollTicker := time.NewTicker(s.outboxPollInterval())
	defer pollTicker.Stop()
	cleanTicker := time.NewTicker(time.Hour)
	defer cleanTicker.Stop()

	for {
		for {
			processed, err := s.processOutboxBatch(ctx)
			if err != nil && ctx.Err() == nil {
				slog.Warn("outbox batch error", "error", err)
				break
			}
			if processed < s.outboxBatchSize() {
				break
			}
		}
		select {
		case <-ctx.Done():
			return
		case <-wake:
		case <-pollTicker.C:
		case <-cleanTicker.C:
			s.cleanupOutbox(ctx)
		}
	}
}

func (s *Server) listenOutboxNotifications(ctx context.Context, wake chan<- struct{}) {
	for ctx.Err() == nil {
		conn, err := s.DB.Acquire(ctx)
		if err != nil {
			select {
			case <-ctx.Done():
				return
			case <-time.After(2 * time.Second):
				continue
			}
		}
		_, err = conn.Exec(ctx, "LISTEN chat_outbox")
		if err != nil {
			conn.Release()
			select {
			case <-ctx.Done():
				return
			case <-time.After(2 * time.Second):
				continue
			}
		}
		for ctx.Err() == nil {
			_, err = conn.Conn().WaitForNotification(ctx)
			if err != nil {
				break
			}
			select {
			case wake <- struct{}{}:
			default:
			}
		}
		conn.Release()
	}
}

func (s *Server) cleanupOutbox(ctx context.Context) {
	cutoff := time.Now().UTC().Add(-s.outboxRetention())
	if _, err := s.DB.Exec(ctx, `DELETE FROM outbox_events WHERE delivered_at IS NOT NULL AND delivered_at < $1`, cutoff); err != nil && ctx.Err() == nil {
		slog.Warn("outbox cleanup failed", "error", err)
	}
}

func (s *Server) processOutboxBatch(ctx context.Context) (int, error) {
	// Phase 1: Claim a batch with a 120s visibility timeout in a single short statement.
	rows, err := s.DB.Query(ctx,
		`UPDATE outbox_events
		 SET next_attempt_at = now() + interval '120 seconds'
		 WHERE id IN (
			SELECT id
			FROM outbox_events
			WHERE delivered_at IS NULL AND next_attempt_at <= now()
			ORDER BY id ASC
			LIMIT $1
			FOR UPDATE SKIP LOCKED
		 )
		 RETURNING id, destination, conversation_id::text, message_id::text, target_id, event_type, payload, attempts`,
		s.outboxBatchSize(),
	)
	if err != nil {
		return 0, err
	}
	var batch []outboxRow
	for rows.Next() {
		var r outboxRow
		if err = rows.Scan(&r.ID, &r.Destination, &r.ConversationID, &r.MessageID, &r.TargetID, &r.EventType, &r.Payload, &r.Attempts); err != nil {
			rows.Close()
			return 0, err
		}
		batch = append(batch, r)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return 0, err
	}
	if len(batch) == 0 {
		return 0, nil
	}

	// Phase 2: Dispatch outside any DB transaction, keeping FIFO order per (destination, conversation, target).
	type dispatchResult struct {
		ev  outboxRow
		err error
	}
	type groupKey struct {
		dest, conv, target string
	}
	type indexedRow struct {
		idx int
		row outboxRow
	}
	grouped := make(map[groupKey][]indexedRow, len(batch))
	var keys []groupKey
	for i, ev := range batch {
		k := groupKey{ev.Destination, ev.ConversationID, ev.TargetID}
		if _, ok := grouped[k]; !ok {
			keys = append(keys, k)
		}
		grouped[k] = append(grouped[k], indexedRow{idx: i, row: ev})
	}
	results := make([]dispatchResult, len(batch))
	sem := make(chan struct{}, 8)
	var wg sync.WaitGroup
	for _, k := range keys {
		items := grouped[k]
		wg.Add(1)
		sem <- struct{}{}
		go func(seq []indexedRow) {
			defer wg.Done()
			defer func() { <-sem }()
			for _, it := range seq {
				dispatchCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
				err := s.dispatchOutboxEvent(dispatchCtx, it.row)
				cancel()
				results[it.idx] = dispatchResult{ev: it.row, err: err}
			}
		}(items)
	}
	wg.Wait()

	// Phase 3: Ack outcomes in a single short transaction.
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback(ctx)

	var settledIDs []int64
	for _, res := range results {
		if res.err == nil {
			settledIDs = append(settledIDs, res.ev.ID)
			continue
		}
		if isPermanentOutboxError(res.err) {
			slog.Warn("settling permanently failed outbox event", "id", res.ev.ID, "destination", res.ev.Destination, "target", res.ev.TargetID, "error", res.err)
			settledIDs = append(settledIDs, res.ev.ID)
			continue
		}
		nextDelay := time.Duration(math.Min(float64(s.outboxMaxBackoff()/time.Second), math.Pow(2, float64(res.ev.Attempts+1)))) * time.Second
		if nextDelay < 2*time.Second {
			nextDelay = 2 * time.Second
		}
		slog.Warn("outbox dispatch failed, scheduling retry", "id", res.ev.ID, "destination", res.ev.Destination, "attempts", res.ev.Attempts+1, "delay", nextDelay, "error", res.err)
		if _, err = tx.Exec(ctx, `UPDATE outbox_events SET attempts=attempts+1, next_attempt_at=now()+$2::interval WHERE id=$1`, res.ev.ID, fmt.Sprintf("%d seconds", int(nextDelay.Seconds()))); err != nil {
			return 0, err
		}
	}
	if len(settledIDs) > 0 {
		if _, err = tx.Exec(ctx, `UPDATE outbox_events SET delivered_at=now(), attempts=attempts+1 WHERE id = ANY($1::bigint[])`, settledIDs); err != nil {
			return 0, err
		}
	}
	if err = tx.Commit(ctx); err != nil {
		return 0, err
	}
	return len(batch), nil
}

func isPermanentOutboxError(err error) bool {
	code := status.Code(err)
	return code == codes.NotFound || code == codes.InvalidArgument || code == codes.FailedPrecondition
}

func (s *Server) dispatchOutboxEvent(ctx context.Context, ev outboxRow) error {
	switch ev.Destination {
	case "centrifugo":
		if s.Centrifugo == nil {
			return nil
		}
		rawChannels := strings.Split(ev.TargetID, ",")
		channels := make([]string, 0, len(rawChannels))
		seen := make(map[string]bool, len(rawChannels))
		for _, ch := range rawChannels {
			ch = strings.TrimSpace(ch)
			if ch != "" && !seen[ch] {
				seen[ch] = true
				channels = append(channels, ch)
			}
		}
		return s.Centrifugo.Broadcast(ctx, channels, map[string]any{
			"type": ev.EventType,
			"data": json.RawMessage(ev.Payload),
		}, false)

	case "leta":
		if s.LetaInternal == nil {
			return nil
		}
		req, err := buildDeliverInboxRequest(ev)
		if err != nil {
			return status.Error(codes.InvalidArgument, err.Error())
		}
		_, err = s.LetaInternal.DeliverInbox(ctx, req)
		return err
	default:
		return nil
	}
}

func buildDeliverInboxRequest(ev outboxRow) (*letapb.DeliverInboxRequest, error) {
	if ev.EventType == "agent.reaction" {
		var p struct {
			WorkspaceID    string `json:"workspace_id"`
			ConversationID string `json:"conversation_id"`
			MessageID      string `json:"message_id"`
			ActorType      string `json:"actor_type"`
			ActorID        string `json:"actor_id"`
			Emoji          string `json:"emoji"`
			Action         string `json:"action"`
		}
		if err := json.Unmarshal(ev.Payload, &p); err != nil {
			return nil, err
		}
		return &letapb.DeliverInboxRequest{
			AgentId:        ev.TargetID,
			IdempotencyKey: fmt.Sprintf("chat:react:%d", ev.ID),
			Event: &letapb.DeliverInboxRequest_ChatReaction{
				ChatReaction: &letapb.ChatReactionEvent{
					WorkspaceId:    p.WorkspaceID,
					ConversationId: p.ConversationID,
					MessageId:      p.MessageID,
					Actor:          &letapb.ActorRef{Type: p.ActorType, Id: p.ActorID},
					Emoji:          p.Emoji,
					Action:         p.Action,
				},
			},
		}, nil
	}

	var p struct {
		WorkspaceID      string           `json:"workspace_id"`
		ConversationID   string           `json:"conversation_id"`
		ConversationType string           `json:"conversation_type"`
		Title            string           `json:"title"`
		Handle           string           `json:"handle"`
		MessageID        string           `json:"message_id"`
		Seq              int64            `json:"seq"`
		SenderType       string           `json:"sender_type"`
		SenderID         string           `json:"sender_id"`
		Content          string           `json:"content"`
		ReplyToID        string           `json:"reply_to_id"`
		Attachments      []attachmentJSON `json:"attachments"`
		Mentions         []mentionJSON    `json:"mentions"`
		Metadata         json.RawMessage  `json:"metadata"`
	}
	if err := json.Unmarshal(ev.Payload, &p); err != nil {
		return nil, err
	}
	atts := make([]*letapb.ChatAttachment, 0, len(p.Attachments))
	for _, a := range p.Attachments {
		atts = append(atts, &letapb.ChatAttachment{
			StorageId: a.StorageID,
			NodeId:    a.NodeID,
			Name:      a.Name,
			MediaType: a.MediaType,
		})
	}
	mentions := make([]*letapb.ChatMention, 0, len(p.Mentions))
	for _, m := range p.Mentions {
		cm := &letapb.ChatMention{
			Kind:  m.Kind,
			Id:    m.ID,
			Label: m.Label,
		}
		if m.StorageID != nil {
			cm.StorageId = *m.StorageID
		}
		if m.NodeID != nil {
			cm.NodeId = *m.NodeID
		}
		mentions = append(mentions, cm)
	}
	idemp := fmt.Sprintf("chat:msg:%s", p.MessageID)
	if p.MessageID == "" {
		idemp = fmt.Sprintf("chat:outbox:%d", ev.ID)
	}
	return &letapb.DeliverInboxRequest{
		AgentId:        ev.TargetID,
		IdempotencyKey: idemp,
		Event: &letapb.DeliverInboxRequest_ChatMessage{
			ChatMessage: &letapb.ChatMessageEvent{
				WorkspaceId:      p.WorkspaceID,
				ConversationId:   p.ConversationID,
				ConversationType: p.ConversationType,
				Title:            p.Title,
				Handle:           p.Handle,
				MessageId:        p.MessageID,
				Seq:              p.Seq,
				Sender:           &letapb.ActorRef{Type: p.SenderType, Id: p.SenderID},
				Content:          p.Content,
				ReplyToMessageId: p.ReplyToID,
				Attachments:      atts,
				Mentions:         mentions,
				MetadataJson:     p.Metadata,
			},
		},
	}, nil
}
