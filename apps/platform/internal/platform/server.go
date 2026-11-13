package platform

import (
	"context"
	"io"
	"time"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	authzed "github.com/authzed/authzed-go/v1"
	"github.com/clerk/clerk-sdk-go/v2/user"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/platform/v1"
	"go.temporal.io/sdk/client"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type Settings struct {
	GRPCListen                  string       `yaml:"grpc_listen"`
	GRPCTarget                  string       `yaml:"grpc_target"`
	Database                    sdk.Database `yaml:"database"`
	MaxMembers                  int          `yaml:"max_members"`
	DefaultQuotaBytes           int64        `yaml:"default_quota_bytes"`
	InvitationTTLSeconds        int          `yaml:"invitation_ttl_seconds"`
	IdempotencyRetentionSeconds int          `yaml:"idempotency_retention_seconds"`
	Maintenance                 struct {
		IntervalSeconds int `yaml:"interval_seconds"`
	} `yaml:"maintenance"`
}
type Server struct {
	DB       *pgxpool.Pool
	Graph    *authzed.Client
	Clerk    *user.Client
	Temporal client.Client
	Settings Settings
	Queues   sdk.Queues
	Queue    string
}

var _ pb.PlatformServiceServer = (*Server)(nil)
var _ pb.PlatformInternalServiceServer = (*Server)(nil)

func human(ctx context.Context) (sdk.Actor, error) {
	a, err := sdk.ActorFromContext(ctx)
	if err != nil {
		return a, err
	}
	if a.Type != "user" {
		return a, status.Error(codes.PermissionDenied, "human user required")
	}
	return a, nil
}
func (s *Server) check(ctx context.Context, workspace, permission string) (sdk.Actor, error) {
	a, err := human(ctx)
	if err != nil {
		return a, err
	}
	result, err := s.Graph.CheckPermission(ctx, &az.CheckPermissionRequest{Resource: sdk.Object("workspace", workspace), Permission: permission, Subject: sdk.Subject(a), Consistency: sdk.Consistency(ctx)})
	if err != nil {
		return a, err
	}
	if result.Permissionship != az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION {
		return a, status.Error(codes.PermissionDenied, "workspace permission denied")
	}
	return a, nil
}
func (s *Server) active(ctx context.Context, id string) error {
	var state string
	err := s.DB.QueryRow(ctx, `SELECT state FROM workspaces WHERE id=$1`, id).Scan(&state)
	if err != nil {
		return err
	}
	if state != "active" {
		return status.Error(codes.FailedPrecondition, "workspace is not active")
	}
	return nil
}
func scanUser(row pgx.Row) (*pb.User, error) {
	u := new(pb.User)
	err := row.Scan(&u.Id, &u.DisplayName, &u.AvatarUrl)
	return u, err
}
func scanWorkspace(row pgx.Row) (*pb.Workspace, error) {
	w := new(pb.Workspace)
	var state string
	var created time.Time
	err := row.Scan(&w.Id, &w.Name, &state, &created)
	w.State = workspaceState(state)
	w.CreatedAt = timestamppb.New(created)
	return w, err
}
func workspaceState(v string) pb.WorkspaceState {
	switch v {
	case "active":
		return pb.WorkspaceState_WORKSPACE_STATE_ACTIVE
	case "deleting":
		return pb.WorkspaceState_WORKSPACE_STATE_DELETING
	default:
		return pb.WorkspaceState_WORKSPACE_STATE_PROVISIONING
	}
}
func pageSize(n int32) uint32 {
	if n == 0 {
		return 50
	}
	return uint32(n)
}
func (s *Server) relationships(ctx context.Context, f *az.RelationshipFilter, limit uint32, cursor string) ([]*az.Relationship, string, error) {
	req := &az.ReadRelationshipsRequest{RelationshipFilter: f, Consistency: sdk.Consistency(ctx), OptionalLimit: limit}
	if cursor != "" {
		req.OptionalCursor = &az.Cursor{Token: cursor}
	}
	stream, err := s.Graph.ReadRelationships(ctx, req)
	if err != nil {
		return nil, "", err
	}
	var out []*az.Relationship
	var next string
	for {
		r, err := stream.Recv()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, "", err
		}
		out = append(out, r.Relationship)
		next = r.AfterResultCursor.Token
	}
	if len(out) < int(limit) {
		next = ""
	}
	return out, next, nil
}
func (s *Server) write(ctx context.Context, updates ...*az.RelationshipUpdate) error {
	_, err := s.Graph.WriteRelationships(ctx, &az.WriteRelationshipsRequest{Updates: updates})
	return err
}
