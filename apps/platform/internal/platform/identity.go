package platform

import (
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"strings"

	"github.com/clerk/clerk-sdk-go/v2/user"
	"github.com/google/uuid"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/platform/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func (s *Server) Onboard(ctx context.Context, _ *emptypb.Empty) (*pb.User, error) {
	subject, err := sdk.ClerkSubject(ctx)
	if err != nil {
		return nil, err
	}
	profile, err := s.Clerk.Get(ctx, subject)
	if err != nil {
		return nil, err
	}
	name := strings.TrimSpace(strings.Join([]string{value(profile.FirstName), value(profile.LastName)}, " "))
	if name == "" {
		name = value(profile.Username)
	}
	if name == "" {
		name = "User"
	}
	u, err := scanUser(s.DB.QueryRow(ctx, `
		WITH inserted AS (
			INSERT INTO users(id, clerk_subject, display_name, avatar_url)
			VALUES($1, $2, $3, $4)
			ON CONFLICT(clerk_subject) DO NOTHING
			RETURNING id, display_name, avatar_url, appearance, handle
		)
		SELECT id, display_name, avatar_url, appearance, handle FROM inserted
		UNION ALL
		SELECT id, display_name, avatar_url, appearance, handle FROM users
		WHERE clerk_subject=$2 AND NOT EXISTS(SELECT 1 FROM inserted)
	`, uuid.NewString(), subject, name, profile.ImageURL))
	if err != nil {
		return nil, err
	}
	key := s.UserIDMetadataKey
	if key == "" {
		key = "openlet_user_id"
	}
	metadata, err := json.Marshal(map[string]string{key: u.Id})
	if err != nil {
		return nil, err
	}
	_, err = s.Clerk.UpdateMetadata(ctx, subject, &user.UpdateMetadataParams{PublicMetadata: (*json.RawMessage)(&metadata)})
	return u, err
}
func value(v *string) string {
	if v == nil {
		return ""
	}
	return *v
}
func (s *Server) GetMe(ctx context.Context, _ *emptypb.Empty) (*pb.User, error) {
	subject, err := sdk.ClerkSubject(ctx)
	if err != nil {
		return nil, err
	}
	u, err := scanUser(s.DB.QueryRow(ctx, `SELECT id,display_name,avatar_url,appearance,handle FROM users WHERE clerk_subject=$1`, subject))
	if err != nil {
		return nil, err
	}
	var preferences []byte
	if err = s.DB.QueryRow(ctx, `SELECT preferences FROM users WHERE id=$1`, u.Id).Scan(&preferences); err != nil {
		return nil, err
	}
	if len(preferences) > 0 {
		u.Preferences = new(pb.AccountPreferences)
		err = protojson.Unmarshal(preferences, u.Preferences)
	}
	return u, err
}
func (s *Server) UpdateMe(ctx context.Context, r *pb.UpdateMeRequest) (*pb.User, error) {
	subject, err := sdk.ClerkSubject(ctx)
	if err != nil {
		return nil, err
	}
	if r.DisplayName != nil {
		name := strings.TrimSpace(*r.DisplayName)
		if name == "" {
			return nil, status.Error(codes.InvalidArgument, "display name cannot be blank")
		}
		r.DisplayName = &name
	}
	var appearance, preferences []byte
	if r.Appearance != nil {
		appearance, err = protojson.Marshal(r.Appearance)
		if err != nil {
			return nil, err
		}
	}
	if r.Preferences != nil {
		preferences, err = protojson.Marshal(r.Preferences)
		if err != nil {
			return nil, err
		}
	}
	result, err := s.DB.Exec(ctx, `UPDATE users SET display_name=coalesce($2,display_name),avatar_url=CASE WHEN $3::text IS NULL THEN avatar_url ELSE nullif($3,'') END,appearance=coalesce($4::jsonb,appearance),preferences=coalesce(preferences,'{}'::jsonb)||coalesce($5::jsonb,'{}'::jsonb) WHERE clerk_subject=$1`, subject, r.DisplayName, r.AvatarUrl, appearance, preferences)
	if err != nil {
		return nil, err
	}
	if result.RowsAffected() == 0 {
		return nil, notFound("user")
	}
	return s.GetMe(ctx, &emptypb.Empty{})
}
func (s *Server) BatchGetUsers(ctx context.Context, r *pb.BatchGetUsersRequest) (*pb.BatchGetUsersResponse, error) {
	rows, err := s.DB.Query(ctx, `SELECT id,display_name,avatar_url,appearance,handle FROM users WHERE id=ANY($1::uuid[])`, r.UserIds)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := new(pb.BatchGetUsersResponse)
	for rows.Next() {
		u, err := scanUser(rows)
		if err != nil {
			return nil, err
		}
		out.Users = append(out.Users, u)
	}
	return out, rows.Err()
}

func (s *Server) GetUserByHandle(ctx context.Context, r *pb.UserHandleRequest) (*pb.User, error) {
	user, err := scanUser(s.DB.QueryRow(ctx, `SELECT id,display_name,avatar_url,appearance,handle FROM users WHERE handle=$1`, r.Handle))
	if err == pgx.ErrNoRows {
		return nil, notFound("user")
	}
	return user, err
}

func (s *Server) GetRealtimeConnectToken(ctx context.Context, _ *emptypb.Empty) (*pb.RealtimeConnectToken, error) {
	a, err := human(ctx)
	if err != nil {
		return nil, err
	}
	if s.CentrifugoSecret == "" {
		return nil, status.Error(codes.FailedPrecondition, "realtime gateway is not configured")
	}
	tok, exp, err := sdk.SignCentrifugoToken(s.CentrifugoSecret, a.ID, "", s.CentrifugoTTL)
	if err != nil {
		return nil, status.Error(codes.Internal, err.Error())
	}
	return &pb.RealtimeConnectToken{
		Token:     tok,
		ExpiresAt: timestamppb.New(exp),
		UserId:    a.ID,
	}, nil
}
