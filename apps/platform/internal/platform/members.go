package platform

import (
	"context"

	statuspb "google.golang.org/genproto/googleapis/rpc/status"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/platform/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/emptypb"
)

func statusFromProto(s *statuspb.Status) error { return status.FromProto(s).Err() }
func notFound(resource string) error           { return status.Error(codes.NotFound, resource+" not found") }
func (s *Server) ListMembers(ctx context.Context, r *pb.ListMembersRequest) (*pb.ListMembersResponse, error) {
	if _, err := s.check(ctx, r.WorkspaceId, "view"); err != nil {
		return nil, err
	}
	rels, next, err := s.relationships(ctx, &az.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: r.WorkspaceId, OptionalSubjectFilter: &az.SubjectFilter{SubjectType: "user"}}, pageSize(r.PageSize), r.PageToken)
	if err != nil {
		return nil, err
	}
	ids := []string{}
	roles := map[string]pb.WorkspaceRole{}
	for _, rel := range rels {
		role := pb.WorkspaceRole_WORKSPACE_ROLE_MEMBER
		if rel.Relation == "owner" {
			role = pb.WorkspaceRole_WORKSPACE_ROLE_OWNER
		}
		id := rel.Subject.Object.ObjectId
		ids = append(ids, id)
		roles[id] = role
	}
	users, err := s.BatchGetUsers(ctx, &pb.BatchGetUsersRequest{UserIds: ids})
	if err != nil {
		return nil, err
	}
	byID := map[string]*pb.User{}
	for _, u := range users.Users {
		byID[u.Id] = u
	}
	out := &pb.ListMembersResponse{NextPageToken: next}
	for _, id := range ids {
		if u := byID[id]; u != nil {
			out.Members = append(out.Members, &pb.WorkspaceMember{User: u, Role: roles[id]})
		}
	}
	return out, nil
}
func (s *Server) AddMember(ctx context.Context, r *pb.AddMemberRequest) (*pb.WorkspaceMember, error) {
	if _, err := s.check(ctx, r.WorkspaceId, "manage"); err != nil {
		return nil, err
	}
	if err := s.active(ctx, r.WorkspaceId); err != nil {
		return nil, err
	}
	u, err := scanUser(s.DB.QueryRow(ctx, `SELECT id,display_name,avatar_url FROM users WHERE id=$1`, r.UserId))
	if err != nil {
		return nil, err
	}
	role, err := s.memberAdmission(ctx, r.WorkspaceId, r.UserId)
	if err != nil {
		return nil, err
	}
	if role != pb.WorkspaceRole_WORKSPACE_ROLE_UNSPECIFIED {
		return &pb.WorkspaceMember{User: u, Role: role}, s.provisionMember(ctx, r.WorkspaceId, r.UserId, r.RequestId, "")
	}
	written, err := s.Graph.WriteRelationships(ctx, &az.WriteRelationshipsRequest{Updates: []*az.RelationshipUpdate{sdk.Touch(sdk.Relation("workspace", r.WorkspaceId, "member", "user", r.UserId, ""))}})
	if err != nil {
		return nil, err
	}
	return &pb.WorkspaceMember{User: u, Role: pb.WorkspaceRole_WORKSPACE_ROLE_MEMBER}, s.provisionMember(ctx, r.WorkspaceId, r.UserId, r.RequestId, written.WrittenAt.Token)
}

func (s *Server) memberAdmission(ctx context.Context, workspaceID, userID string) (pb.WorkspaceRole, error) {
	rels, _, err := s.relationships(ctx, &az.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: workspaceID, OptionalSubjectFilter: &az.SubjectFilter{SubjectType: "user"}}, uint32(s.Settings.MaxMembers+1), "")
	if err != nil {
		return pb.WorkspaceRole_WORKSPACE_ROLE_UNSPECIFIED, err
	}
	for _, rel := range rels {
		if rel.Subject.Object.ObjectId == userID {
			role := pb.WorkspaceRole_WORKSPACE_ROLE_MEMBER
			if rel.Relation == "owner" {
				role = pb.WorkspaceRole_WORKSPACE_ROLE_OWNER
			}
			return role, nil
		}
	}
	if len(rels) >= s.Settings.MaxMembers {
		return pb.WorkspaceRole_WORKSPACE_ROLE_UNSPECIFIED, status.Error(codes.ResourceExhausted, "workspace member limit reached")
	}
	return pb.WorkspaceRole_WORKSPACE_ROLE_UNSPECIFIED, nil
}
func (s *Server) TransferWorkspaceOwnership(ctx context.Context, r *pb.TransferWorkspaceOwnershipRequest) (*pb.WorkspaceMember, error) {
	a, err := s.check(ctx, r.WorkspaceId, "manage")
	if err != nil {
		return nil, err
	}
	if err = s.active(ctx, r.WorkspaceId); err != nil {
		return nil, err
	}
	u, err := scanUser(s.DB.QueryRow(ctx, `SELECT id,display_name,avatar_url FROM users WHERE id=$1`, r.NewOwnerUserId))
	if err != nil {
		return nil, err
	}
	out := &pb.WorkspaceMember{User: u, Role: pb.WorkspaceRole_WORKSPACE_ROLE_OWNER}
	if a.ID == r.NewOwnerUserId {
		return out, nil
	}
	owner := sdk.Relation("workspace", r.WorkspaceId, "owner", "user", a.ID, "")
	member := sdk.Relation("workspace", r.WorkspaceId, "member", "user", r.NewOwnerUserId, "")
	_, err = s.Graph.WriteRelationships(ctx, &az.WriteRelationshipsRequest{OptionalPreconditions: []*az.Precondition{
		{Operation: az.Precondition_OPERATION_MUST_MATCH, Filter: &az.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: r.WorkspaceId, OptionalRelation: "owner", OptionalSubjectFilter: &az.SubjectFilter{SubjectType: "user", OptionalSubjectId: a.ID}}},
		{Operation: az.Precondition_OPERATION_MUST_MATCH, Filter: &az.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: r.WorkspaceId, OptionalRelation: "member", OptionalSubjectFilter: &az.SubjectFilter{SubjectType: "user", OptionalSubjectId: r.NewOwnerUserId}}},
	}, Updates: []*az.RelationshipUpdate{sdk.Delete(owner), sdk.Delete(member), sdk.Touch(sdk.Relation("workspace", r.WorkspaceId, "member", "user", a.ID, "")), sdk.Touch(sdk.Relation("workspace", r.WorkspaceId, "owner", "user", r.NewOwnerUserId, ""))}})
	return out, err
}
func (s *Server) RemoveMember(ctx context.Context, r *pb.RemoveMemberRequest) (*emptypb.Empty, error) {
	a, err := human(ctx)
	if err != nil {
		return nil, err
	}
	if a.ID != r.UserId {
		if _, err = s.check(ctx, r.WorkspaceId, "manage"); err != nil {
			return nil, err
		}
	}
	if err = s.active(ctx, r.WorkspaceId); err != nil {
		return nil, err
	}
	updates := []*az.RelationshipUpdate{sdk.Delete(sdk.Relation("workspace", r.WorkspaceId, "member", "user", r.UserId, ""))}
	_, err = s.Graph.WriteRelationships(ctx, &az.WriteRelationshipsRequest{Updates: updates, OptionalPreconditions: []*az.Precondition{{Operation: az.Precondition_OPERATION_MUST_NOT_MATCH, Filter: &az.RelationshipFilter{ResourceType: "workspace", OptionalResourceId: r.WorkspaceId, OptionalRelation: "owner", OptionalSubjectFilter: &az.SubjectFilter{SubjectType: "user", OptionalSubjectId: r.UserId}}}}})
	return &emptypb.Empty{}, err
}
func (s *Server) CheckWorkspaceActive(ctx context.Context, r *pb.CheckWorkspaceActiveRequest) (*emptypb.Empty, error) {
	return &emptypb.Empty{}, s.active(ctx, r.WorkspaceId)
}
