package rpc

import (
	"context"
	"errors"

	"github.com/qninhdt/openlet/packages/go/apperr"

	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// Fault preserves the application error code across native gRPC and HTTP.
func Fault(code codes.Code, reason, message string) error {
	s, err := status.New(code, message).WithDetails(&errdetails.ErrorInfo{Domain: "openlet", Reason: reason})
	if err != nil {
		return status.Error(codes.Internal, "internal server error")
	}
	return s.Err()
}

// NormalizeError keeps trusted application faults and hides dependency details on both transports.
func NormalizeError(err error) error {
	if err == nil {
		return nil
	}
	if fault, ok := apperr.As(err); ok {
		return Fault(grpcCode(fault.Kind), fault.Reason, fault.Message)
	}
	if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
		err = status.FromContextError(err).Err()
	}
	s := status.Convert(err)
	for _, detail := range s.Details() {
		if info, ok := detail.(*errdetails.ErrorInfo); ok && info.Domain == "openlet" && info.Reason != "" {
			return s.Err()
		}
	}
	grpcCode := s.Code()
	if grpcCode == codes.Unknown {
		grpcCode = codes.Internal
	}
	code, message := errorDescription(grpcCode)
	return Fault(grpcCode, code, message)
}

func errorDescription(grpcCode codes.Code) (string, string) {
	code, message := "INTERNAL", "internal server error"
	switch grpcCode {
	case codes.InvalidArgument, codes.OutOfRange:
		code, message = "VALIDATION", "invalid request"
	case codes.Unauthenticated:
		code, message = "UNAUTHENTICATED", "authentication required"
	case codes.PermissionDenied:
		code, message = "FORBIDDEN", "permission denied"
	case codes.NotFound:
		code, message = "NOT_FOUND", "resource not found"
	case codes.AlreadyExists, codes.Aborted, codes.FailedPrecondition:
		code, message = "SCOPE_CONFLICT", "operation conflicts with current state"
	case codes.ResourceExhausted:
		code, message = "RESOURCE_LIMIT", "resource limit exceeded"
	case codes.Unavailable:
		code, message = "DEPENDENCY_UNAVAILABLE", "dependency unavailable"
	case codes.Canceled:
		code, message = "CANCELED", "request canceled"
	case codes.DeadlineExceeded:
		code, message = "TIMEOUT", "request deadline exceeded"
	case codes.Unimplemented:
		code, message = "NOT_IMPLEMENTED", "method not implemented"
	}
	return code, message
}

var kinds = map[codes.Code]apperr.Kind{
	codes.Internal:        apperr.Internal,
	codes.InvalidArgument: apperr.Invalid, codes.Unauthenticated: apperr.Unauthenticated,
	codes.PermissionDenied: apperr.Forbidden, codes.NotFound: apperr.Missing,
	codes.AlreadyExists: apperr.Exists, codes.Aborted: apperr.Conflict,
	codes.FailedPrecondition: apperr.Precondition, codes.ResourceExhausted: apperr.Limit,
	codes.Unavailable: apperr.Unavailable, codes.Canceled: apperr.Canceled,
	codes.DeadlineExceeded: apperr.Timeout, codes.Unimplemented: apperr.Unsupported,
	codes.OutOfRange: apperr.OutOfRange,
}

func grpcCode(kind apperr.Kind) codes.Code {
	for code, candidate := range kinds {
		if candidate == kind {
			return code
		}
	}
	return codes.Internal
}

// DecodeError stops remote transport errors escaping into application code.
func DecodeError(err error) error {
	if err == nil {
		return nil
	}
	if _, ok := apperr.As(err); ok {
		return err
	}
	s := status.Convert(NormalizeError(err))
	reason, message := errorDescription(s.Code())
	for _, detail := range s.Details() {
		if info, ok := detail.(*errdetails.ErrorInfo); ok && info.Domain == "openlet" && info.Reason != "" {
			reason, message = info.Reason, s.Message()
			break
		}
	}
	kind, ok := kinds[s.Code()]
	if !ok {
		kind = apperr.Internal
	}
	return apperr.New(kind, reason, message)
}
