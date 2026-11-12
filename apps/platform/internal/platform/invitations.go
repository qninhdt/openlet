package platform

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/platform/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func scanInvitation(row pgx.Row) (*pb.Invitation, error) {
	r := new(pb.Invitation)
	var expires time.Time
	err := row.Scan(&r.Id, &r.WorkspaceId, &r.Email, &expires, &r.AcceptedByUserId)
	r.ExpiresAt = timestamppb.New(expires)
	return r, err
}
func (s *Server) CreateInvitation(ctx context.Context, r *pb.CreateInvitationRequest) (*pb.CreateInvitationResponse, error) {
	a, err := s.check(ctx, r.WorkspaceId, "manage")
	if err != nil {
		return nil, err
	}
	if err = s.active(ctx, r.WorkspaceId); err != nil {
		return nil, err
	}
	tokenBytes := make([]byte, 32)
	if _, err = rand.Read(tokenBytes); err != nil {
		return nil, err
	}
	token := base64.RawURLEncoding.EncodeToString(tokenBytes)
	hash := sha256.Sum256([]byte(token))
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	out := new(pb.CreateInvitationResponse)
	duplicate, err := sdk.Claim(ctx, tx, a.String(), "CreateInvitation", r.RequestId, r, out, s.receiptTTL())
	if err != nil {
		return nil, err
	}
	if duplicate {
		return out, tx.Commit(ctx)
	}
	out.Invitation, err = scanInvitation(tx.QueryRow(ctx, `INSERT INTO invitations(id,workspace_id,email,token_hash,expires_at) SELECT $1,id,$3,$4,$5 FROM workspaces WHERE id=$2 AND state='active' RETURNING id,workspace_id,email,expires_at,accepted_by`, uuid.NewString(), r.WorkspaceId, strings.ToLower(r.Email), hash[:], time.Now().Add(time.Duration(s.Settings.InvitationTTLSeconds)*time.Second)))
	if err != nil {
		return nil, err
	}
	if err = sdk.Finish(ctx, tx, a.String(), "CreateInvitation", r.RequestId, out); err != nil {
		return nil, err
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, err
	}
	out.Token = &token
	return out, nil
}
func (s *Server) ListInvitations(ctx context.Context, r *pb.ListInvitationsRequest) (*pb.ListInvitationsResponse, error) {
	if _, err := s.check(ctx, r.WorkspaceId, "manage"); err != nil {
		return nil, err
	}
	if r.PageToken != "" {
		if _, err := uuid.Parse(r.PageToken); err != nil {
			return nil, status.Error(codes.InvalidArgument, "invalid invitation cursor")
		}
	}
	rows, err := s.DB.Query(ctx, `SELECT id,workspace_id,email,expires_at,accepted_by FROM invitations WHERE workspace_id=$1 AND ($2::uuid IS NULL OR id>$2) ORDER BY id LIMIT $3`, r.WorkspaceId, nullable(r.PageToken), pageSize(r.PageSize)+1)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := new(pb.ListInvitationsResponse)
	for rows.Next() {
		v, err := scanInvitation(rows)
		if err != nil {
			return nil, err
		}
		out.Invitations = append(out.Invitations, v)
	}
	if err = rows.Err(); err != nil {
		return nil, err
	}
	if len(out.Invitations) > int(pageSize(r.PageSize)) {
		out.Invitations = out.Invitations[:pageSize(r.PageSize)]
		out.NextPageToken = out.Invitations[len(out.Invitations)-1].Id
	}
	return out, nil
}
func nullable(v string) any {
	if v == "" {
		return nil
	}
	return v
}
func (s *Server) RevokeInvitation(ctx context.Context, r *pb.RevokeInvitationRequest) (*emptypb.Empty, error) {
	if _, err := s.check(ctx, r.WorkspaceId, "manage"); err != nil {
		return nil, err
	}
	_, err := s.DB.Exec(ctx, `DELETE FROM invitations WHERE workspace_id=$1 AND id=$2`, r.WorkspaceId, r.InvitationId)
	return &emptypb.Empty{}, err
}
func (s *Server) AcceptInvitation(ctx context.Context, r *pb.AcceptInvitationRequest) (*pb.WorkspaceMember, error) {
	a, err := human(ctx)
	if err != nil {
		return nil, err
	}
	subject, err := sdk.ClerkSubject(ctx)
	if err != nil {
		return nil, err
	}
	profile, err := s.Clerk.Get(ctx, subject)
	if err != nil {
		return nil, err
	}
	emails := []string{}
	for _, e := range profile.EmailAddresses {
		if e.Verification != nil && e.Verification.Status == "verified" {
			emails = append(emails, strings.ToLower(e.EmailAddress))
		}
	}
	h := sha256.Sum256([]byte(r.Token))
	var workspaceID string
	var acceptedBy *string
	err = s.DB.QueryRow(ctx, `SELECT i.workspace_id,i.accepted_by FROM invitations i JOIN workspaces w ON w.id=i.workspace_id
 WHERE i.token_hash=$1 AND i.email=ANY($3::text[]) AND w.state='active'
 AND ((i.accepted_by IS NULL AND i.expires_at>now()) OR i.accepted_by=$2)`, h[:], a.ID, emails).Scan(&workspaceID, &acceptedBy)
	if err != nil {
		return nil, err
	}
	if acceptedBy != nil {
		if _, err = s.check(ctx, workspaceID, "view"); err != nil {
			return nil, status.Error(codes.FailedPrecondition, "invitation was already consumed; request a new invitation")
		}
	} else {
		if _, err = s.memberAdmission(ctx, workspaceID, a.ID); err != nil {
			return nil, err
		}
		err = s.DB.QueryRow(ctx, `UPDATE invitations i SET accepted_by=$2 FROM workspaces w
 WHERE i.token_hash=$1 AND i.accepted_by IS NULL AND i.expires_at>now()
 AND w.id=i.workspace_id AND w.state='active' RETURNING i.workspace_id`, h[:], a.ID).Scan(&workspaceID)
		if err != nil {
			return nil, err
		}
		written, err := s.Graph.WriteRelationships(ctx, &az.WriteRelationshipsRequest{Updates: []*az.RelationshipUpdate{sdk.Touch(sdk.Relation("workspace", workspaceID, "member", "user", a.ID, ""))}})
		if err != nil {
			return nil, err
		}
		// A consumed invite is not replayed as a grant after a later revocation.
		if err = s.provisionMember(ctx, workspaceID, a.ID, hexHash(h[:]), written.WrittenAt.Token); err != nil {
			return nil, err
		}
	}
	u, err := scanUser(s.DB.QueryRow(ctx, `SELECT id,display_name,avatar_url FROM users WHERE id=$1`, a.ID))
	return &pb.WorkspaceMember{User: u, Role: pb.WorkspaceRole_WORKSPACE_ROLE_MEMBER}, err
}
