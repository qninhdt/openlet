package chat

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"

	"github.com/google/uuid"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/chat/v1"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type CentrifugoClient struct {
	APIURL string
	APIKey string
	HTTP   *http.Client
}

func (c *CentrifugoClient) Broadcast(ctx context.Context, channels []string, data any, skipHistory bool) error {
	if c == nil || c.APIURL == "" || len(channels) == 0 {
		return nil
	}
	body, err := json.Marshal(map[string]any{
		"channels":     channels,
		"data":         data,
		"skip_history": skipHistory,
	})
	if err != nil {
		return err
	}
	endpoint := strings.TrimRight(c.APIURL, "/") + "/broadcast"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.APIKey != "" {
		req.Header.Set("X-API-Key", c.APIKey)
	}
	client := c.HTTP
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1024))
		return fmt.Errorf("centrifugo broadcast status %d: %s", resp.StatusCode, strings.TrimSpace(string(raw)))
	}
	return nil
}

func (s *Server) SetTyping(ctx context.Context, r *pb.SetTypingRequest) (*emptypb.Empty, error) {
	caller, err := s.check(ctx, "conversation", r.ConversationId, "participate")
	if err != nil {
		return nil, err
	}
	if s.Centrifugo != nil {
		_ = s.Centrifugo.Broadcast(ctx, []string{convChannel(r.ConversationId)}, map[string]any{
			"type": "typing",
			"data": map[string]any{
				"workspace_id":    r.WorkspaceId,
				"conversation_id": r.ConversationId,
				"actor_type":      caller.Type,
				"actor_id":        caller.ID,
				"active":          r.Active,
			},
		}, true)
	}
	return &emptypb.Empty{}, nil
}

func parseConvChannelID(channel string) (string, bool) {
	if !strings.HasPrefix(channel, "chat:conv:") {
		return "", false
	}
	id := strings.TrimPrefix(channel, "chat:conv:")
	if _, err := uuid.Parse(id); err != nil {
		return "", false
	}
	return id, true
}

func (s *Server) GetRealtimeToken(ctx context.Context, r *pb.GetRealtimeTokenRequest) (*pb.RealtimeTokenResponse, error) {
	convID, ok := parseConvChannelID(r.Channel)
	if !ok {
		return nil, invalid("channel must be chat:conv:<conversation_uuid>")
	}
	caller, err := s.check(ctx, "conversation", convID, "view")
	if err != nil {
		return nil, err
	}
	if caller.Type != "user" {
		return nil, permissionDenied("realtime tokens are for human users")
	}
	var exists bool
	if err = s.DB.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM conversations WHERE id=$1 AND workspace_id=$2)`, convID, r.WorkspaceId).Scan(&exists); err != nil {
		return nil, err
	}
	if !exists {
		return nil, notFound("conversation")
	}
	tok, exp, err := sdk.SignCentrifugoToken(s.CentrifugoSecret, caller.ID, r.Channel, s.CentrifugoTTL)
	if err != nil {
		return nil, err
	}
	return &pb.RealtimeTokenResponse{
		Token:     tok,
		ExpiresAt: timestamppb.New(exp),
		Channel:   r.Channel,
	}, nil
}
