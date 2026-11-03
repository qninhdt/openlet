package identity

import (
	"context"

	"github.com/google/uuid"
)

type Principal struct {
	Service string
	ActorID uuid.UUID
	Subject string
	Gateway bool
}

type principalKey struct{}

func WithPrincipal(ctx context.Context, principal Principal) context.Context {
	return context.WithValue(ctx, principalKey{}, principal)
}

func FromContext(ctx context.Context) (Principal, bool) {
	principal, ok := ctx.Value(principalKey{}).(Principal)
	return principal, ok
}
