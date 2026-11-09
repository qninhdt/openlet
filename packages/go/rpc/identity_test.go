package rpc

import (
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/metadata"
)

func TestWithActorReplacesDelegationWithoutMutatingCallerMetadata(t *testing.T) {
	original := metadata.Pairs("x-openlet-user-id", uuid.NewString(), "x-openlet-leta-id", uuid.NewString(), "traceparent", "context")
	ctx := metadata.NewOutgoingContext(t.Context(), original)
	actor := uuid.New()
	delegated, err := WithActor(ctx, identity.Actor{Kind: identity.User, ID: actor})
	require.NoError(t, err)
	outgoing, ok := metadata.FromOutgoingContext(delegated)
	require.True(t, ok)
	require.Equal(t, []string{actor.String()}, outgoing.Get("x-openlet-user-id"))
	require.Equal(t, []string{"context"}, outgoing.Get("traceparent"))
	require.NotEqual(t, original.Get("x-openlet-user-id"), outgoing.Get("x-openlet-user-id"))
	require.Empty(t, outgoing.Get("x-openlet-leta-id"))
	delegated, err = WithActor(ctx, identity.Actor{Kind: identity.Leta, ID: actor})
	require.NoError(t, err)
	outgoing, _ = metadata.FromOutgoingContext(delegated)
	require.Empty(t, outgoing.Get("x-openlet-user-id"))
	require.Equal(t, []string{actor.String()}, outgoing.Get("x-openlet-leta-id"))
	_, err = WithActor(ctx, identity.Actor{Kind: "account", ID: actor})
	require.Error(t, err)
}
