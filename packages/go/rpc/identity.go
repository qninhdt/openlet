package rpc

import (
	"context"
	"errors"

	"github.com/qninhdt/openlet/packages/go/identity"
	"google.golang.org/grpc/metadata"
)

// WithActor explicitly delegates an actor on outbound calls; the receiver controls permission to delegate.
func WithActor(ctx context.Context, actor identity.Actor) (context.Context, error) {
	if !actor.Valid() {
		return nil, errors.New("invalid actor identity")
	}
	outgoing, _ := metadata.FromOutgoingContext(ctx)
	outgoing = outgoing.Copy()
	outgoing.Delete("x-openlet-user-id")
	outgoing.Delete("x-openlet-leta-id")
	outgoing.Delete("x-openlet-account-id")
	outgoing.Set("x-openlet-"+string(actor.Kind)+"-id", actor.ID.String())
	return metadata.NewOutgoingContext(ctx, outgoing), nil
}
