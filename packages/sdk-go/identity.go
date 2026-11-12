package sdk

import (
	"context"
	"strings"

	"github.com/google/uuid"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

type Actor struct{ Type, ID string }

func (a Actor) String() string { return a.Type + ":" + a.ID }
func ActorFromContext(ctx context.Context) (Actor, error) {
	md, _ := metadata.FromIncomingContext(ctx)
	users, agents := md.Get("x-openlet-user-id"), md.Get("x-openlet-agent-id")
	var a Actor
	if len(users) == 1 && len(agents) == 0 {
		a = Actor{"user", users[0]}
	} else if len(agents) == 1 && len(users) == 0 {
		a = Actor{"agent", agents[0]}
	} else {
		return a, status.Error(codes.Unauthenticated, "one verified actor is required")
	}
	if _, err := uuid.Parse(a.ID); err != nil {
		return Actor{}, status.Error(codes.Unauthenticated, "invalid actor identity")
	}
	return a, nil
}
func ClerkSubject(ctx context.Context) (string, error) {
	md, _ := metadata.FromIncomingContext(ctx)
	values := md.Get("x-openlet-clerk-subject")
	if len(values) != 1 || strings.TrimSpace(values[0]) == "" {
		return "", status.Error(codes.Unauthenticated, "verified Clerk subject is required")
	}
	return values[0], nil
}
func WithActor(ctx context.Context, a Actor) context.Context {
	key := "x-openlet-" + a.Type + "-id"
	return metadata.AppendToOutgoingContext(ctx, key, a.ID)
}
