package identity

import (
	"context"

	"github.com/google/uuid"
)

type ActorKind string

const (
	User ActorKind = "user"
	Leta ActorKind = "leta"
)

type Actor struct {
	Kind ActorKind `json:"kind"`
	ID   uuid.UUID `json:"id"`
}

func (a Actor) Valid() bool    { return (a.Kind == User || a.Kind == Leta) && a.ID != uuid.Nil }
func (a Actor) String() string { return string(a.Kind) + ":" + a.ID.String() }

type Principal struct {
	Service   string
	ActorID   uuid.UUID
	ActorKind ActorKind
	Subject   string
	Gateway   bool
}

func (p Principal) Actor() Actor { return Actor{Kind: p.ActorKind, ID: p.ActorID} }

type principalKey struct{}

func WithPrincipal(ctx context.Context, principal Principal) context.Context {
	return context.WithValue(ctx, principalKey{}, principal)
}

func FromContext(ctx context.Context) (Principal, bool) {
	principal, ok := ctx.Value(principalKey{}).(Principal)
	return principal, ok
}
