package rpc

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/account/internal/account"
	accountv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/account/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	sharedrpc "github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/status"
)

type Server struct {
	accountv1.UnimplementedAccountServiceServer
	healthv1.UnimplementedHealthServer
	GraphReady func(context.Context) error
	Service    *account.Service
}

func (s *Server) Check(ctx context.Context, request *healthv1.HealthCheckRequest) (*healthv1.HealthCheckResponse, error) {
	if request.GetService() != "" && request.GetService() != accountv1.AccountService_ServiceDesc.ServiceName {
		return nil, status.Error(codes.NotFound, "unknown service")
	}
	state := healthv1.HealthCheckResponse_SERVING
	if s.GraphReady == nil || s.GraphReady(ctx) != nil || s.Service.Store.DB.Ping(ctx) != nil {
		state = healthv1.HealthCheckResponse_NOT_SERVING
	}
	return &healthv1.HealthCheckResponse{Status: state}, nil
}

func workspaceCaller(ctx context.Context) error {
	principal, ok := identity.FromContext(ctx)
	if !ok || principal.Gateway || principal.Service != "workspace" || principal.ActorID != uuid.Nil {
		return sharedrpc.Fault(codes.PermissionDenied, "FORBIDDEN", "workspace service authority required")
	}
	return nil
}

func storeError(err error) error {
	if err == nil {
		return nil
	}
	var fault account.Fault
	if errors.As(err, &fault) {
		switch fault.Code {
		case "NOT_FOUND":
			return sharedrpc.Fault(codes.NotFound, fault.Code, "active user not found")
		case "VALIDATION":
			return sharedrpc.Fault(codes.InvalidArgument, fault.Code, "invalid user lookup")
		}
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		return err
	}
	return sharedrpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "account dependency unavailable")
}

func (s *Server) GetAccountSummaries(ctx context.Context, input *accountv1.GetAccountSummariesRequest) (*accountv1.GetAccountSummariesResponse, error) {
	if err := workspaceCaller(ctx); err != nil {
		return nil, err
	}
	values := input.GetIds()
	if len(values) == 0 || len(values) > 100 {
		return nil, storeError(account.Fault{Code: "VALIDATION"})
	}
	ids := make([]uuid.UUID, len(values))
	seen := make(map[uuid.UUID]bool, len(values))
	for index, value := range values {
		id, err := uuid.Parse(value)
		if err != nil || id == uuid.Nil || seen[id] {
			return nil, storeError(account.Fault{Code: "VALIDATION"})
		}
		ids[index], seen[id] = id, true
	}
	profiles, err := s.Service.Store.Summaries(ctx, ids)
	if err != nil {
		return nil, storeError(err)
	}
	result := &accountv1.GetAccountSummariesResponse{Accounts: make([]*accountv1.AccountSummary, 0, len(profiles))}
	for _, profile := range profiles {
		result.Accounts = append(result.Accounts, &accountv1.AccountSummary{Id: profile.ID.String(), DisplayName: profile.DisplayName, AvatarUrl: profile.AvatarURL})
	}
	return result, nil
}

func (s *Server) GetVerifiedEmails(ctx context.Context, input *accountv1.GetVerifiedEmailsRequest) (*accountv1.GetVerifiedEmailsResponse, error) {
	if err := workspaceCaller(ctx); err != nil {
		return nil, err
	}
	id, err := uuid.Parse(input.GetAccountId())
	if err != nil || id == uuid.Nil {
		return nil, storeError(account.Fault{Code: "VALIDATION"})
	}
	emails, err := s.Service.VerifiedEmails(ctx, id)
	if err != nil {
		return nil, storeError(err)
	}
	return &accountv1.GetVerifiedEmailsResponse{Emails: emails}, nil
}
