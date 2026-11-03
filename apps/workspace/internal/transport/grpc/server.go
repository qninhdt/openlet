package grpc

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/workspace/internal/workspace"
	workspacev1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/workspace/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedrpc "github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"
)

type Server struct {
	workspacev1.UnimplementedWorkspaceAdministrationServiceServer
	healthv1.UnimplementedHealthServer
	Service *workspace.Service
	Ready   func(context.Context) error
}

func (s *Server) Check(ctx context.Context, request *healthv1.HealthCheckRequest) (*healthv1.HealthCheckResponse, error) {
	if request.GetService() != "" && request.GetService() != workspacev1.WorkspaceAdministrationService_ServiceDesc.ServiceName {
		return nil, status.Error(codes.NotFound, "unknown service")
	}
	state := healthv1.HealthCheckResponse_SERVING
	if s.Ready == nil || s.Ready(ctx) != nil {
		state = healthv1.HealthCheckResponse_NOT_SERVING
	}
	return &healthv1.HealthCheckResponse{Status: state}, nil
}

func accountCaller(ctx context.Context) error {
	principal, ok := identity.FromContext(ctx)
	if !ok || principal.Gateway || principal.Service != "account" || principal.ActorID != uuid.Nil {
		return sharedrpc.Fault(codes.PermissionDenied, "FORBIDDEN", "account service authority required")
	}
	return nil
}

func serviceError(err error) error {
	if err == nil {
		return nil
	}
	var fault workspace.Fault
	if errors.As(err, &fault) {
		code := codes.FailedPrecondition
		if fault.Code == "VALIDATION" {
			code = codes.InvalidArgument
		}
		return sharedrpc.Fault(code, fault.Code, "workspace request failed")
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	return sharedrpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "workspace dependency unavailable")
}

func (s *Server) EnsureInitialWorkspace(ctx context.Context, request *workspacev1.EnsureInitialWorkspaceRequest) (*workspacev1.EnsureInitialWorkspaceResponse, error) {
	if err := accountCaller(ctx); err != nil {
		return nil, err
	}
	actor, actorErr := uuid.Parse(request.GetActorId())
	key, keyErr := uuid.Parse(request.GetRequestKey())
	if actorErr != nil || keyErr != nil || actor == uuid.Nil || key == uuid.Nil {
		return nil, serviceError(workspace.Fault{Code: "VALIDATION"})
	}
	value, completed, err := s.Service.EnsureInitial(ctx, workspace.CreateInput{ActorID: actor, Key: key, Name: request.GetName()})
	if err != nil {
		return nil, serviceError(err)
	}
	return &workspacev1.EnsureInitialWorkspaceResponse{WorkspaceId: value.ID.String(), Completed: completed}, nil
}
