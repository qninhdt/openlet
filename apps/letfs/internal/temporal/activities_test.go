package temporal

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/require"
	"go.temporal.io/sdk/temporal"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"openlet/packages/go/rpc"
)

func TestActivityErrorClassificationDoesNotLeakDependencyDetails(t *testing.T) {
	require.NoError(t, activityError(nil))
	require.True(t, temporal.IsCanceledError(activityError(context.Canceled)))
	for _, scenario := range []struct {
		err      error
		reason   string
		terminal bool
	}{
		{rpc.Fault(codes.Aborted, "SOURCE_REPLACED", "source changed"), "SOURCE_REPLACED", true},
		{rpc.Fault(codes.ResourceExhausted, "QUOTA_EXCEEDED", "quota"), "QUOTA_EXCEEDED", true},
		{rpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "private endpoint"), "DEPENDENCY_UNAVAILABLE", false},
		{errors.New("postgres password or provider response"), "DEPENDENCY_UNAVAILABLE", false},
		{context.DeadlineExceeded, "DEPENDENCY_UNAVAILABLE", false},
	} {
		var application *temporal.ApplicationError
		err := activityError(scenario.err)
		require.ErrorAs(t, err, &application)
		require.Equal(t, scenario.reason, application.Type())
		require.Equal(t, scenario.terminal, application.NonRetryable())
		require.Equal(t, scenario.reason, application.Message())
		require.Nil(t, application.Unwrap())
	}
	require.True(t, temporal.IsCanceledError(activityError(status.Error(codes.Canceled, "request canceled"))))
}
