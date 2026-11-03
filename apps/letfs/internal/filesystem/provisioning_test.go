package filesystem

import (
	"context"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"openlet/packages/go/identity"
)

func TestProvisioningRequiresServiceBeforeStorage(t *testing.T) {
	s := &Store{}
	for _, ctx := range []context.Context{t.Context(), identity.WithPrincipal(t.Context(), identity.Principal{Service: "gateway", Gateway: true})} {
		_, err := s.CreateBucket(ctx, uuid.New(), CreateBucket{ID: uuid.Must(uuid.NewV7()), LimitBytes: 100})
		require.Equal(t, codes.PermissionDenied, status.Code(err))
	}
}

func TestStableStorageIdentityAndExactNames(t *testing.T) {
	require.Error(t, requestIdentity(uuid.New(), uuid.New()))
	require.Error(t, requestIdentity(uuid.Must(uuid.NewV7()), uuid.Nil))
	require.NoError(t, requestIdentity(uuid.Must(uuid.NewV7()), uuid.New()))
	for _, name := range []string{"", ".", "..", "a/b", "a\x00b", strings.Repeat("x", 256), string([]byte{255})} {
		require.Error(t, ValidateName(name), "%q", name)
	}
	for _, name := range []string{"a\\b", "Việt Nam", strings.Repeat("x", 255)} {
		require.NoError(t, ValidateName(name))
	}
}
