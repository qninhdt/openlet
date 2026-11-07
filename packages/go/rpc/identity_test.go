package rpc

import (
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/metadata"
)

func TestWithActorReplacesDelegationWithoutMutatingCallerMetadata(t *testing.T) {
	original := metadata.Pairs("x-openlet-account-id", uuid.NewString(), "traceparent", "context")
	ctx := metadata.NewOutgoingContext(t.Context(), original)
	actor := uuid.New()
	outgoing, ok := metadata.FromOutgoingContext(WithActor(ctx, actor))
	require.True(t, ok)
	require.Equal(t, []string{actor.String()}, outgoing.Get("x-openlet-account-id"))
	require.Equal(t, []string{"context"}, outgoing.Get("traceparent"))
	require.NotEqual(t, original.Get("x-openlet-account-id"), outgoing.Get("x-openlet-account-id"))
}
