package chat

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"buf.build/go/protovalidate"
	"github.com/google/uuid"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/chat/v1"
	"google.golang.org/protobuf/proto"
)

func TestCanonicalDMKeyAndSlugify(t *testing.T) {
	u1 := sdk.Actor{Type: "user", ID: "00000000-0000-0000-0000-000000000001"}
	a1 := sdk.Actor{Type: "agent", ID: "00000000-0000-0000-0000-000000000002"}
	if canonicalDMKey(u1, a1) != canonicalDMKey(a1, u1) {
		t.Fatalf("DM key must be symmetric")
	}
	if canonicalDMKey(u1, a1) != "agent:00000000-0000-0000-0000-000000000002|user:00000000-0000-0000-0000-000000000001" {
		t.Fatalf("unexpected dm key: %s", canonicalDMKey(u1, a1))
	}
	if got := slugifyHandle("Q3 Deal Room — Project Pluto!"); got != "q3-deal-room-project-pluto" {
		t.Fatalf("unexpected slug: %q", got)
	}
	if got := slugifyHandle("   !!!   "); got != "group" {
		t.Fatalf("expected fallback group, got %q", got)
	}
}

func TestValidateSidebarLayout(t *testing.T) {
	cid := uuid.NewString()
	p1 := "f1"
	p2 := "f2"
	p3 := "f3"

	validLayout := &pb.SidebarLayout{
		Folders: []*pb.SidebarFolder{
			{Id: "f1", Name: "Root", Order: 0},
			{Id: "f2", Name: "Sub", ParentId: &p1, Order: 0},
			{Id: "f3", Name: "Leaf", ParentId: &p2, Order: 0},
		},
		Assignments: map[string]string{cid: "f3"},
		Pins:        []string{cid},
	}
	if err := validateSidebarLayout(validLayout); err != nil {
		t.Fatalf("expected 3-level layout valid: %v", err)
	}

	tooDeep := &pb.SidebarLayout{
		Folders: []*pb.SidebarFolder{
			{Id: "f1", Name: "L1"},
			{Id: "f2", Name: "L2", ParentId: &p1},
			{Id: "f3", Name: "L3", ParentId: &p2},
			{Id: "f4", Name: "L4", ParentId: &p3},
		},
	}
	if err := validateSidebarLayout(tooDeep); err == nil {
		t.Fatal("expected depth 4 folder to be rejected")
	}

	cycle := &pb.SidebarLayout{
		Folders: []*pb.SidebarFolder{
			{Id: "f1", Name: "A", ParentId: &p2},
			{Id: "f2", Name: "B", ParentId: &p1},
		},
	}
	if err := validateSidebarLayout(cycle); err == nil {
		t.Fatal("expected cyclic folder tree to be rejected")
	}
}

func TestOutboxBuildDeliverInboxRequest(t *testing.T) {
	wsID, convID, msgID, senderID, agentID := uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString()
	storageID, nodeID := uuid.NewString(), uuid.NewString()
	msgPayload, _ := json.Marshal(map[string]any{
		"workspace_id":      wsID,
		"conversation_id":   convID,
		"conversation_type": "dm",
		"message_id":        msgID,
		"seq":               7,
		"sender_type":       "user",
		"sender_id":         senderID,
		"content":           "Check [report](/letfs/" + storageID + "/" + nodeID + ")",
		"attachments":       []map[string]any{{"storage_id": storageID, "node_id": nodeID, "name": "r.pdf", "media_type": "application/pdf"}},
		"mentions":          []map[string]any{{"kind": "file", "id": nodeID, "storage_id": storageID, "node_id": nodeID, "label": "report"}},
	})
	req, err := buildDeliverInboxRequest(outboxRow{
		ID:             1,
		Destination:    "leta",
		ConversationID: convID,
		MessageID:      &msgID,
		TargetID:       agentID,
		EventType:      "agent.message",
		Payload:        msgPayload,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := protovalidate.Validate(req); err != nil {
		t.Fatalf("message inbox req failed validation: %v", err)
	}
	msgEv := req.GetChatMessage()
	if msgEv == nil || msgEv.ConversationId != convID || req.IdempotencyKey != "chat:msg:"+msgID || len(msgEv.Attachments) != 1 || msgEv.Attachments[0].NodeId != nodeID || len(msgEv.Mentions) != 1 || msgEv.Mentions[0].Kind != "file" || msgEv.Mentions[0].NodeId != nodeID {
		t.Fatalf("unexpected message inbox req: %+v", req)
	}

	reactPayload, _ := json.Marshal(map[string]any{
		"workspace_id":    wsID,
		"conversation_id": convID,
		"message_id":      msgID,
		"actor_type":      "user",
		"actor_id":        senderID,
		"emoji":           "👍",
		"action":          "added",
	})
	reactReq, err := buildDeliverInboxRequest(outboxRow{
		ID:             42,
		Destination:    "leta",
		ConversationID: convID,
		MessageID:      &msgID,
		TargetID:       agentID,
		EventType:      "agent.reaction",
		Payload:        reactPayload,
	})
	if err != nil {
		t.Fatal(err)
	}
	if err := protovalidate.Validate(reactReq); err != nil {
		t.Fatalf("reaction inbox req failed validation: %v", err)
	}
	reactEv := reactReq.GetChatReaction()
	if reactEv == nil || reactEv.Emoji != "👍" || reactEv.Action != "added" || reactReq.IdempotencyKey != "chat:react:42" {
		t.Fatalf("unexpected reaction inbox req: %+v", reactReq)
	}
}

func TestCentrifugoBroadcastAndChannelParsing(t *testing.T) {
	cid := uuid.NewString()
	gotID, ok := parseConvChannelID("chat:conv:" + cid)
	if !ok || gotID != cid {
		t.Fatalf("parseConvChannelID failed: %v %q", ok, gotID)
	}
	if _, ok := parseConvChannelID("chat:user#" + cid); ok {
		t.Fatal("personal channel must not be accepted by GetRealtimeToken")
	}

	var captured map[string]any
	var gotKey string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotKey = r.Header.Get("X-API-Key")
		_ = json.NewDecoder(r.Body).Decode(&captured)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{}`))
	}))
	defer srv.Close()

	client := &CentrifugoClient{APIURL: srv.URL + "/api", APIKey: "k-123"}
	if err := client.Broadcast(context.Background(), []string{"chat:user#u1", "chat:conv:" + cid}, map[string]string{"type": "typing"}, true); err != nil {
		t.Fatal(err)
	}
	if gotKey != "k-123" || captured["skip_history"] != true {
		t.Fatalf("unexpected broadcast: key=%q body=%+v", gotKey, captured)
	}
}

func TestChatRequestValidation(t *testing.T) {
	id := uuid.NewString()
	for _, tc := range []struct {
		name  string
		msg   proto.Message
		valid bool
	}{
		{"valid dm", &pb.CreateOrGetDMRequest{WorkspaceId: id, Target: &pb.ChatActor{Type: "agent", Id: id}}, true},
		{"invalid actor type", &pb.CreateOrGetDMRequest{WorkspaceId: id, Target: &pb.ChatActor{Type: "bot", Id: id}}, false},
		{"valid group", &pb.CreateGroupRequest{WorkspaceId: id, Title: "Deal Room", Handle: proto.String("deal-room")}, true},
		{"invalid group handle", &pb.CreateGroupRequest{WorkspaceId: id, Title: "Deal Room", Handle: proto.String("Deal Room!")}, false},
		{"valid list messages around", &pb.ListMessagesRequest{WorkspaceId: id, ConversationId: id, AroundSeq: proto.Int64(5), Limit: 50}, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			err := protovalidate.Validate(tc.msg)
			if (err == nil) != tc.valid {
				t.Fatalf("valid=%v err=%v", tc.valid, err)
			}
		})
	}
}
