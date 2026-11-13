package platform

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"strings"

	"github.com/clerk/clerk-sdk-go/v2/user"
	"github.com/google/uuid"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/platform/v1"
	enums "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/client"
	"google.golang.org/grpc"
	grpcmetadata "google.golang.org/grpc/metadata"
	"google.golang.org/protobuf/types/known/emptypb"
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
	input := ProvisionInput{LetFSQueue: s.Queues.LetFS, Subject: subject, UserID: uuid.NewString(), WorkspaceID: uuid.NewString(), SharedStorageID: uuid.NewString(), SharedRootID: uuid.NewString(), PrivateStorageID: uuid.NewString(), PrivateRootID: uuid.NewString(), Name: name + "'s workspace", DisplayName: name, AvatarURL: profile.ImageURL, Quota: s.Settings.DefaultQuotaBytes}
	h := sha256.Sum256([]byte(subject))
	run, err := s.Temporal.ExecuteWorkflow(ctx, client.StartWorkflowOptions{ID: "onboard/" + hex.EncodeToString(h[:]), TaskQueue: s.Queue, WorkflowIDReusePolicy: enums.WORKFLOW_ID_REUSE_POLICY_REJECT_DUPLICATE, WorkflowIDConflictPolicy: enums.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING}, ProvisionWorkspace, input)
	if err != nil {
		return nil, err
	}
	var result ProvisionResult
	if err = run.Get(ctx, &result); err != nil {
		return nil, err
	}
	if result.ZedToken != "" {
		if err = grpc.SetHeader(ctx, grpcmetadata.Pairs("x-openlet-zed-token", result.ZedToken)); err != nil {
			return nil, err
		}
	}
	metadata, err := json.Marshal(map[string]string{"openlet_user_id": result.User.Id})
	if err != nil {
		return nil, err
	}
	_, err = s.Clerk.UpdateMetadata(ctx, subject, &user.UpdateMetadataParams{PublicMetadata: (*json.RawMessage)(&metadata)})
	return result.User, err
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
	return scanUser(s.DB.QueryRow(ctx, `SELECT id,display_name,avatar_url FROM users WHERE clerk_subject=$1`, subject))
}
func (s *Server) UpdateMe(ctx context.Context, r *pb.UpdateMeRequest) (*pb.User, error) {
	subject, err := sdk.ClerkSubject(ctx)
	if err != nil {
		return nil, err
	}
	return scanUser(s.DB.QueryRow(ctx, `UPDATE users SET display_name=coalesce($2,display_name),avatar_url=CASE WHEN $3::text IS NULL THEN avatar_url ELSE nullif($3,'') END WHERE clerk_subject=$1 RETURNING id,display_name,avatar_url`, subject, r.DisplayName, r.AvatarUrl))
}
func (s *Server) BatchGetUsers(ctx context.Context, r *pb.BatchGetUsersRequest) (*pb.BatchGetUsersResponse, error) {
	rows, err := s.DB.Query(ctx, `SELECT id,display_name,avatar_url FROM users WHERE id=ANY($1::uuid[])`, r.UserIds)
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
