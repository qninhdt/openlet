package rpc

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"testing"

	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/httpapi"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func TestApplicationErrorsKeepNativeAndHTTPContracts(t *testing.T) {
	for _, test := range []struct {
		grpc   codes.Code
		reason string
		http   int
	}{
		{codes.FailedPrecondition, "PRECONDITION_REQUIRED", 428},
		{codes.FailedPrecondition, "REVISION_MISMATCH", 412},
		{codes.FailedPrecondition, "TARGET_MISMATCH", 412},
		{codes.NotFound, "COPY_EXPIRED", 410},
		{codes.ResourceExhausted, "REQUEST_LIMIT", 413},
		{codes.OutOfRange, "INVALID_RANGE", 416},
		{codes.NotFound, "NOT_FOUND", 404},
		{codes.Aborted, "IDEMPOTENCY_CONFLICT", 409},
	} {
		t.Run(test.reason, func(t *testing.T) {
			err := Fault(test.grpc, test.reason, "safe explanation")
			require.Equal(t, test.grpc, status.Code(err))
			r := httptest.NewRequest("GET", "/", nil)
			r.Header.Set("X-Request-ID", "request")
			w := httptest.NewRecorder()
			httpapi.WriteError(w, r, DecodeError(err))
			require.Equal(t, test.http, w.Code)
			require.Equal(t, "application/problem+json", w.Header().Get("Content-Type"))
			require.Equal(t, "no-store", w.Header().Get("Cache-Control"))
			var body map[string]any
			require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))
			require.Equal(t, test.reason, body["code"])
			require.Equal(t, "safe explanation", body["detail"])
			require.Equal(t, "request", body["request_id"])
		})
	}
}

func TestNativeInterceptorSanitizesHandlerErrors(t *testing.T) {
	const method = "/openlet_api.letfs.v1.FilesystemService/GetNode"
	const token = "isolated-service-credential-1234567890"
	authentication, err := NewAuthenticator([]Credential{{Service: "fixture", Token: token, Methods: []string{method}}})
	require.NoError(t, err)
	for _, test := range []struct {
		name    string
		err     error
		code    codes.Code
		message string
	}{
		{"driver", errors.New("password=secret"), codes.Internal, "internal server error"},
		{"dependency status", status.Error(codes.Unavailable, "signed URL=secret"), codes.Unavailable, "dependency unavailable"},
		{"application fault", Fault(codes.Aborted, "IDEMPOTENCY_CONFLICT", "safe explanation"), codes.Aborted, "safe explanation"},
		{"canceled", context.Canceled, codes.Canceled, "request canceled"},
		{"deadline", context.DeadlineExceeded, codes.DeadlineExceeded, "request deadline exceeded"},
	} {
		t.Run(test.name, func(t *testing.T) {
			ctx := metadata.NewIncomingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+token))
			_, err := authentication.Unary()(ctx, nil, &grpc.UnaryServerInfo{FullMethod: method}, func(context.Context, any) (any, error) { return nil, test.err })
			s := status.Convert(err)
			require.Equal(t, test.code, s.Code())
			require.Equal(t, test.message, s.Message())
			require.Len(t, s.Details(), 1)
			require.NotContains(t, s.Message(), "secret")
		})
	}
}

func TestDependencyAndUnexpectedErrorsDoNotLeakDetails(t *testing.T) {
	for _, err := range []error{errors.New("database password=secret"), status.Error(codes.Unavailable, "signed URL=secret")} {
		w := httptest.NewRecorder()
		httpapi.WriteError(w, httptest.NewRequest("GET", "/", nil), DecodeError(err))
		require.NotContains(t, w.Body.String(), "secret")
		require.Contains(t, []int{500, 503}, w.Code)
	}
}

func TestNativeErrorRoundTrip(t *testing.T) {
	for kind := apperr.Internal; kind <= apperr.OutOfRange; kind++ {
		original := apperr.New(kind, "SAFE_REASON", "safe message")
		decoded, ok := apperr.As(DecodeError(NormalizeError(original)))
		require.True(t, ok)
		require.Equal(t, kind, decoded.Kind)
		require.Equal(t, "SAFE_REASON", decoded.Reason)
	}
	require.Equal(t, apperr.Internal, apperr.KindOf(DecodeError(errors.New("unexpected secret"))))
	require.Equal(t, apperr.Internal, apperr.KindOf(DecodeError(status.Error(codes.DataLoss, "secret"))))
	require.Nil(t, DecodeError(nil))
}
