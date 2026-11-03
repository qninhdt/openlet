package rpc

import (
	"context"

	"github.com/google/uuid"
	"google.golang.org/grpc/metadata"
)

// WithActor explicitly delegates an actor on outbound calls; the receiver controls permission to delegate.
func WithActor(ctx context.Context, actor uuid.UUID) context.Context {
	outgoing, _ := metadata.FromOutgoingContext(ctx)
	outgoing = outgoing.Copy()
	outgoing.Set("x-openlet-user-id", actor.String())
	return metadata.NewOutgoingContext(ctx, outgoing)
}
