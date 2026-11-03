package filesystem

import (
	"context"
	"time"

	"github.com/google/uuid"
	"google.golang.org/grpc/codes"
	"openlet/packages/go/authz"
	"openlet/packages/go/identity"
	"openlet/packages/go/rpc"
)

func (s *Store) authorize(ctx context.Context, id uuid.UUID, kind string, action authz.Action) (uuid.UUID, error) {
	principal, ok := identity.FromContext(ctx)
	if !ok || principal.ActorID == uuid.Nil {
		return uuid.Nil, rpc.Fault(codes.Unauthenticated, "UNAUTHENTICATED", "verified actor required")
	}
	if id == uuid.Nil {
		return uuid.Nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "resource identity required")
	}
	if s.Graph == nil {
		return uuid.Nil, rpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "authorization unavailable")
	}
	check, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	allowed, err := authz.Check(check, s.Graph, principal.ActorID.String(), action, authz.Resource{Type: kind, ID: id.String()})
	if err != nil {
		if ctx.Err() != nil {
			return uuid.Nil, ctx.Err()
		}
		return uuid.Nil, rpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "authorization unavailable")
	}
	if !allowed {
		return uuid.Nil, rpc.Fault(codes.PermissionDenied, "FORBIDDEN", "permission denied")
	}
	return principal.ActorID, nil
}
