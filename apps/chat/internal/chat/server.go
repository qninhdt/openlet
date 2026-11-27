package chat

import (
	"context"
	"encoding/json"
	"regexp"
	"strings"
	"time"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	authzed "github.com/authzed/authzed-go/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/chat/v1"
	letapb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/leta/v1"
	letfspb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

type OutboxSettings struct {
	BatchSize           int `yaml:"batch_size"`
	PollIntervalSeconds int `yaml:"poll_interval_seconds"`
	MaxBackoffSeconds   int `yaml:"max_backoff_seconds"`
	RetentionHours      int `yaml:"retention_hours"`
}

type Settings struct {
	GRPCListen string         `yaml:"grpc_listen"`
	GRPCTarget string         `yaml:"grpc_target"`
	Database   sdk.Database   `yaml:"database"`
	Outbox     OutboxSettings `yaml:"outbox"`
}

type Server struct {
	DB               *pgxpool.Pool
	Graph            *authzed.Client
	LetFS            letfspb.LetFSServiceClient
	LetFSInternal    letfspb.LetFSInternalServiceClient
	LetaInternal     letapb.LetaInternalServiceClient
	Centrifugo       *CentrifugoClient
	CentrifugoSecret string
	CentrifugoTTL    time.Duration
	Settings         Settings
}

var _ pb.ChatServiceServer = (*Server)(nil)
var _ pb.ChatInternalServiceServer = (*Server)(nil)

type queryer interface {
	Query(context.Context, string, ...any) (pgx.Rows, error)
	QueryRow(context.Context, string, ...any) pgx.Row
	Exec(context.Context, string, ...any) (pgconn.CommandTag, error)
}

func permissionDenied(msg string) error {
	if msg == "" {
		msg = "chat permission denied"
	}
	return status.Error(codes.PermissionDenied, msg)
}

func invalid(msg string) error { return status.Error(codes.InvalidArgument, msg) }
func notFound(what string) error {
	return status.Error(codes.NotFound, what+" not found")
}
func conflict(msg string) error { return status.Error(codes.Aborted, msg) }

func newUUIDv7() string {
	id, err := uuid.NewV7()
	if err != nil {
		return uuid.NewString()
	}
	return id.String()
}

var slugNonAlnum = regexp.MustCompile(`[^a-z0-9]+`)

func slugifyHandle(input string) string {
	s := strings.ToLower(strings.TrimSpace(input))
	s = slugNonAlnum.ReplaceAllString(s, "-")
	s = strings.Trim(s, "-")
	if len(s) > 64 {
		s = strings.TrimRight(s[:64], "-")
	}
	if s == "" {
		return "group"
	}
	return s
}

func canonicalDMKey(a, b sdk.Actor) string {
	sa, sb := a.String(), b.String()
	if sa <= sb {
		return sa + "|" + sb
	}
	return sb + "|" + sa
}

func (s *Server) check(ctx context.Context, kind, id, permission string) (sdk.Actor, error) {
	a, err := sdk.ActorFromContext(ctx)
	if err != nil {
		return a, err
	}
	if err := s.checkActor(ctx, a, kind, id, permission); err != nil {
		return a, err
	}
	return a, nil
}

func (s *Server) checkActor(ctx context.Context, actor sdk.Actor, kind, id, permission string) error {
	cons := sdk.Consistency(ctx)
	r, err := s.Graph.CheckPermission(ctx, &az.CheckPermissionRequest{
		Resource:    sdk.Object(kind, id),
		Permission:  permission,
		Subject:     sdk.Subject(actor),
		Consistency: cons,
	})
	if err != nil {
		return err
	}
	if r.Permissionship != az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION && !cons.GetFullyConsistent() {
		r, err = s.Graph.CheckPermission(ctx, &az.CheckPermissionRequest{
			Resource:    sdk.Object(kind, id),
			Permission:  permission,
			Subject:     sdk.Subject(actor),
			Consistency: &az.Consistency{Requirement: &az.Consistency_FullyConsistent{FullyConsistent: true}},
		})
		if err != nil {
			return err
		}
	}
	if r.Permissionship != az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION {
		return permissionDenied(kind + "#" + permission + " denied")
	}
	return nil
}

func (s *Server) checkActorInWorkspace(ctx context.Context, workspaceID string, actor sdk.Actor) error {
	if actor.Type == "user" {
		return s.checkActor(ctx, actor, "workspace", workspaceID, "participate")
	}
	return s.checkActor(ctx, actor, "workspace", workspaceID, "eligible_actor")
}

func (s *Server) verifyTargetAccessible(ctx context.Context, caller sdk.Actor, workspaceID string, target sdk.Actor) error {
	if err := s.checkActorInWorkspace(ctx, workspaceID, target); err != nil {
		return err
	}
	if target.Type == "agent" && caller.Type == "user" {
		if err := s.checkActor(ctx, caller, "agent", target.ID, "use"); err != nil {
			return err
		}
	}
	return nil
}

func (s *Server) writeRelations(ctx context.Context, updates ...*az.RelationshipUpdate) error {
	if len(updates) == 0 {
		return nil
	}
	resp, err := s.Graph.WriteRelationships(ctx, &az.WriteRelationshipsRequest{Updates: updates})
	if err != nil {
		return err
	}
	if tok := resp.GetWrittenAt().GetToken(); tok != "" {
		_ = grpc.SetHeader(ctx, metadata.Pairs("x-openlet-zed-token", tok))
	}
	return nil
}

func pageSize(n int32) int {
	if n <= 0 {
		return 50
	}
	if n > 100 {
		return 100
	}
	return int(n)
}

func insertOutbox(ctx context.Context, q queryer, destination, convID string, msgID *string, targetID, eventType string, payload any) error {
	raw, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	_, err = q.Exec(ctx,
		`INSERT INTO outbox_events(destination, conversation_id, message_id, target_id, event_type, payload)
		 VALUES($1, $2, $3, $4, $5, $6::jsonb)`,
		destination, convID, msgID, targetID, eventType, string(raw),
	)
	return err
}

func notifyOutbox(ctx context.Context, q queryer) error {
	_, err := q.Exec(ctx, `SELECT pg_notify('chat_outbox', '')`)
	return err
}

func userChannel(userID string) string {
	return "chat:user#" + userID
}

func convChannel(convID string) string {
	return "chat:conv:" + convID
}

func (s *Server) loadMemberChannels(ctx context.Context, q queryer, convID string) (humanChannels []string, agentIDs []string, err error) {
	rows, err := q.Query(ctx, `SELECT actor_type, actor_id::text FROM conversation_members WHERE conversation_id=$1`, convID)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var t, id string
		if err = rows.Scan(&t, &id); err != nil {
			return nil, nil, err
		}
		if t == "user" {
			humanChannels = append(humanChannels, userChannel(id))
		} else if t == "agent" {
			agentIDs = append(agentIDs, id)
		}
	}
	return humanChannels, agentIDs, rows.Err()
}
