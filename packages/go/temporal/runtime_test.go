package temporal

import (
	"context"
	"errors"
	"testing"

	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/stretchr/testify/require"
	sdk "go.temporal.io/sdk/temporal"
)

func TestSafeActivityFailures(t *testing.T) {
	require.Nil(t, Error(nil))
	require.True(t, sdk.IsCanceledError(Error(context.Canceled)))
	for _, test := range []struct {
		err      error
		kind     string
		terminal bool
	}{
		{apperr.New(apperr.Invalid, "VALIDATION", "invalid name"), "VALIDATION", true},
		{apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "dependency unavailable"), "DEPENDENCY_UNAVAILABLE", false},
		{errors.New("password=secret"), "INTERNAL", false},
	} {
		var fault *sdk.ApplicationError
		require.ErrorAs(t, Error(test.err), &fault)
		require.Equal(t, test.kind, fault.Type())
		require.Equal(t, test.terminal, fault.NonRetryable())
		require.NotContains(t, fault.Error(), "secret")
	}
}
