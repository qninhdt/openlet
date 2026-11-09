package rpc

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	"github.com/qninhdt/openlet/packages/go/authz"
	accountv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/account/v1"
	workspacev1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/workspace/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedrpc "github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"
)

type Server struct {
	workspacev1.UnimplementedWorkspaceServiceServer
	healthv1.UnimplementedHealthServer
	Service *workspace.Service
	Ready   func(context.Context) error
}

func Credential(token string) sharedrpc.Credential {
	return sharedrpc.Credential{Service: "leta", Token: token, DelegateActor: true, Methods: []string{
		workspacev1.WorkspaceService_GetWorkspace_FullMethodName,
		workspacev1.WorkspaceService_ListMembers_FullMethodName,
		workspacev1.WorkspaceService_ListAccessibleScopes_FullMethodName,
		workspacev1.WorkspaceService_EnsureLetaHomeAccess_FullMethodName,
		workspacev1.WorkspaceService_ResolvePersonalScope_FullMethodName,
		workspacev1.WorkspaceService_ChangeScopeAccess_FullMethodName,
		workspacev1.WorkspaceService_CleanupLetaAccess_FullMethodName,
	}, LetaMethods: []string{
		workspacev1.WorkspaceService_GetWorkspace_FullMethodName,
		workspacev1.WorkspaceService_ListMembers_FullMethodName,
		workspacev1.WorkspaceService_ListAccessibleScopes_FullMethodName,
		workspacev1.WorkspaceService_ResolvePersonalScope_FullMethodName,
	}}
}

func caller(ctx context.Context) (identity.Actor, error) {
	p, ok := identity.FromContext(ctx)
	if !ok || p.Gateway || p.Service != "leta" {
		return identity.Actor{}, workspace.Fault{Code: "FORBIDDEN"}
	}
	if p.ActorID == uuid.Nil && p.ActorKind == "" {
		return identity.Actor{}, nil
	}
	if !p.Actor().Valid() {
		return identity.Actor{}, workspace.Fault{Code: "FORBIDDEN"}
	}
	return p.Actor(), nil
}

func id(value string) (uuid.UUID, error) {
	parsed, err := uuid.Parse(value)
	if err != nil || parsed == uuid.Nil {
		return uuid.Nil, workspace.Fault{Code: "VALIDATION"}
	}
	return parsed, nil
}

func nativeWorkspace(value workspace.Workspace) *workspacev1.Workspace {
	result := &workspacev1.Workspace{Id: value.ID.String(), Name: value.Name, FilesystemId: value.FilesystemID.String(), SharedScopeId: value.SharedScopeID.String(), Status: value.Status}
	if value.Role != "" {
		result.Role = &value.Role
	}
	if value.PersonalScopeID != uuid.Nil {
		v := value.PersonalScopeID.String()
		result.PersonalScopeId = &v
	}
	return result
}
func summary(value workspace.UserSummary) *accountv1.UserSummary {
	return &accountv1.UserSummary{Id: value.ID.String(), DisplayName: value.DisplayName, AvatarUrl: value.AvatarURL}
}

func (s *Server) Check(ctx context.Context, in *healthv1.HealthCheckRequest) (*healthv1.HealthCheckResponse, error) {
	if in.GetService() != "" && in.GetService() != workspacev1.WorkspaceService_ServiceDesc.ServiceName {
		return nil, status.Error(codes.NotFound, "unknown service")
	}
	state := healthv1.HealthCheckResponse_SERVING
	if s.Ready == nil || s.Ready(ctx) != nil {
		state = healthv1.HealthCheckResponse_NOT_SERVING
	}
	return &healthv1.HealthCheckResponse{Status: state}, nil
}

func (s *Server) GetWorkspace(ctx context.Context, in *workspacev1.GetWorkspaceRequest) (*workspacev1.GetWorkspaceResponse, error) {
	actor, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	ws, err := id(in.GetWorkspaceId())
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	var value workspace.Workspace
	if in.CleanupLetaId != nil {
		if actor.Valid() {
			return nil, workspace.Fault{Code: "FORBIDDEN"}
		}
		root, err := id(in.GetCleanupLetaId())
		if err != nil {
			return nil, err
		}
		value, err = s.Service.CleanupWorkspace(ctx, ws, root)
		if err != nil {
			return nil, err
		}
	} else {
		if !actor.Valid() {
			return nil, workspace.Fault{Code: "FORBIDDEN"}
		}
		value, err = s.Service.ResourceWorkspace(ctx, ws, actor)
		if err != nil {
			return nil, err
		}
	}
	return &workspacev1.GetWorkspaceResponse{Workspace: nativeWorkspace(value)}, nil
}

func (s *Server) ListMembers(ctx context.Context, in *workspacev1.ListMembersRequest) (*workspacev1.ListMembersResponse, error) {
	actor, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if !actor.Valid() {
		return nil, workspace.Fault{Code: "FORBIDDEN"}
	}
	ws, err := id(in.GetWorkspaceId())
	if err != nil {
		return nil, err
	}
	after := uuid.Nil
	if in.Cursor != nil {
		after, err = id(*in.Cursor)
		if err != nil {
			return nil, err
		}
	}
	if in.Limit < 1 || in.Limit > 100 {
		return nil, workspace.Fault{Code: "VALIDATION"}
	}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	items, next, err := s.Service.ResourceMembers(ctx, ws, actor, after, int(in.Limit))
	if err != nil {
		return nil, err
	}
	result := &workspacev1.ListMembersResponse{WorkspaceId: ws.String()}
	for _, item := range items {
		result.Items = append(result.Items, &workspacev1.Member{User: summary(item.User), Role: item.Role, PersonalScopeId: item.PersonalScopeID.String()})
	}
	if next != nil {
		v := next.String()
		result.NextCursor = &v
	}
	return result, nil
}

func (s *Server) ListAccessibleScopes(ctx context.Context, in *workspacev1.ListAccessibleScopesRequest) (*workspacev1.ListAccessibleScopesResponse, error) {
	actor, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if !actor.Valid() {
		return nil, workspace.Fault{Code: "FORBIDDEN"}
	}
	ws, err := id(in.GetWorkspaceId())
	if err != nil {
		return nil, err
	}
	subject, inspector := actor, uuid.Nil
	if in.LetaId != nil {
		if actor.Kind != identity.User {
			return nil, workspace.Fault{Code: "FORBIDDEN"}
		}
		root, err := id(*in.LetaId)
		if err != nil {
			return nil, err
		}
		subject, inspector = identity.Actor{Kind: identity.Leta, ID: root}, actor.ID
	}
	page, err := s.Service.AccessibleScopes(ctx, ws, subject, inspector, in.Cursor, in.Limit)
	if err != nil {
		return nil, err
	}
	result := &workspacev1.ListAccessibleScopesResponse{WorkspaceId: ws.String(), FilesystemId: page.FilesystemID.String(), SubjectKind: string(page.Subject.Kind), SubjectId: page.Subject.ID.String(), NextCursor: page.NextCursor}
	for _, item := range page.Items {
		value := &workspacev1.AccessibleScope{Id: item.ID.String(), RootId: item.RootID.String(), Kind: item.Kind, Rights: &workspacev1.ScopeRights{ReadMetadata: item.ReadMetadata, ReadContent: item.ReadContent, Write: item.Write}}
		if item.Owner != nil {
			value.Owner = summary(*item.Owner)
		}
		result.Items = append(result.Items, value)
	}
	return result, nil
}

func (s *Server) EnsureLetaHomeAccess(ctx context.Context, in *workspacev1.EnsureLetaHomeAccessRequest) (*workspacev1.EnsureLetaHomeAccessResponse, error) {
	actor, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if actor.Kind != identity.User {
		return nil, workspace.Fault{Code: "FORBIDDEN"}
	}
	ws, err := id(in.GetWorkspaceId())
	if err != nil {
		return nil, err
	}
	root, err := id(in.GetLetaId())
	if err != nil {
		return nil, err
	}
	home, err := id(in.GetHomeScopeId())
	if err != nil {
		return nil, err
	}
	key, err := id(in.GetIdempotencyKey())
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()
	value, err := s.Service.EnsureLetaHomeAccess(ctx, workspace.Mutation{Kind: "leta-home", WorkspaceID: ws, ActorID: actor.ID, TargetID: root, ScopeID: home, Key: key})
	if err != nil {
		return nil, err
	}
	return &workspacev1.EnsureLetaHomeAccessResponse{WorkspaceId: ws.String(), FilesystemId: value.FilesystemID.String(), HomeScopeId: home.String()}, nil
}

func (s *Server) ResolvePersonalScope(ctx context.Context, in *workspacev1.ResolvePersonalScopeRequest) (*workspacev1.ResolvePersonalScopeResponse, error) {
	actor, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if actor.Kind != identity.Leta {
		return nil, workspace.Fault{Code: "FORBIDDEN"}
	}
	ws, err := id(in.GetWorkspaceId())
	if err != nil {
		return nil, err
	}
	owner, err := id(in.GetOwnerUserId())
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	value, err := s.Service.ResolvePersonalScope(ctx, ws, actor.ID, owner)
	if err != nil {
		return nil, err
	}
	return &workspacev1.ResolvePersonalScopeResponse{WorkspaceId: ws.String(), FilesystemId: value.FilesystemID.String(), ScopeId: value.ScopeID.String(), OwnerUserId: owner.String()}, nil
}

func (s *Server) ChangeScopeAccess(ctx context.Context, in *workspacev1.ChangeScopeAccessRequest) (*workspacev1.ChangeScopeAccessResponse, error) {
	actor, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if actor.Kind != identity.User {
		return nil, workspace.Fault{Code: "FORBIDDEN"}
	}
	ws, err := id(in.GetWorkspaceId())
	if err != nil {
		return nil, err
	}
	scope, err := id(in.GetScopeId())
	if err != nil {
		return nil, err
	}
	target, err := id(in.GetGranteeId())
	if err != nil {
		return nil, err
	}
	key, err := id(in.GetIdempotencyKey())
	if err != nil {
		return nil, err
	}
	owner := uuid.Nil
	if in.PersonalOwnerUserId != nil {
		owner, err = id(*in.PersonalOwnerUserId)
		if err != nil {
			return nil, err
		}
	}
	ctx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()
	subject := identity.Actor{Kind: identity.ActorKind(in.GetGranteeKind()), ID: target}
	_, err = s.Service.ChangeTypedScopeAccess(ctx, workspace.Mutation{Kind: "scope", WorkspaceID: ws, ActorID: actor.ID, ScopeID: scope, TargetID: target, TargetKind: subject.Kind, ScopeRole: in.GetRole(), Revoke: in.GetRevoke(), Key: key, PersonalOwnerID: owner})
	if err != nil {
		return nil, err
	}
	rights := &workspacev1.ScopeRights{}
	for action, dest := range map[authz.Action]*bool{authz.ScopeReadMetadata: &rights.ReadMetadata, authz.ScopeReadContent: &rights.ReadContent, authz.ScopeWrite: &rights.Write} {
		check, stop := context.WithTimeout(ctx, 2*time.Second)
		*dest, err = authz.Check(check, s.Service.Store.Graph, subject, action, authz.Resource{Type: "scope", ID: scope.String()})
		stop()
		if err != nil {
			return nil, err
		}
	}
	return &workspacev1.ChangeScopeAccessResponse{WorkspaceId: ws.String(), ScopeId: scope.String(), GranteeKind: string(subject.Kind), GranteeId: target.String(), Rights: rights}, nil
}

func (s *Server) CleanupLetaAccess(ctx context.Context, in *workspacev1.CleanupLetaAccessRequest) (*workspacev1.CleanupLetaAccessResponse, error) {
	actor, err := caller(ctx)
	if err != nil {
		return nil, err
	}
	if actor.Valid() && actor.Kind != identity.User {
		return nil, workspace.Fault{Code: "FORBIDDEN"}
	}
	ws, err := id(in.GetWorkspaceId())
	if err != nil {
		return nil, err
	}
	root, err := id(in.GetLetaId())
	if err != nil {
		return nil, err
	}
	home, err := id(in.GetHomeScopeId())
	if err != nil {
		return nil, err
	}
	if err = s.Service.CleanupLetaAccess(ctx, ws, root, home, actor); err != nil {
		return nil, err
	}
	return &workspacev1.CleanupLetaAccessResponse{Completed: true}, nil
}
