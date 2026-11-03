package rpc

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"

	"github.com/grpc-ecosystem/grpc-gateway/v2/runtime"
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

// WriteHTTPError is for errors before response headers; stream failures abort the response.
func WriteHTTPError(w http.ResponseWriter, r *http.Request, err error) {
	s := status.Convert(NormalizeError(err))
	code, message := errorDescription(s.Code())
	for _, detail := range s.Details() {
		if info, ok := detail.(*errdetails.ErrorInfo); ok && info.Domain == "openlet" && info.Reason != "" {
			code, message = info.Reason, s.Message()
			break
		}
	}
	responseStatus := runtime.HTTPStatusFromCode(s.Code())
	switch code {
	case "PRECONDITION_REQUIRED":
		responseStatus = http.StatusPreconditionRequired
	case "REVISION_MISMATCH", "TARGET_MISMATCH":
		responseStatus = http.StatusPreconditionFailed
	case "COPY_EXPIRED":
		responseStatus = http.StatusGone
	case "REQUEST_LIMIT":
		responseStatus = http.StatusRequestEntityTooLarge
	case "INVALID_RANGE":
		responseStatus = http.StatusRequestedRangeNotSatisfiable
	}
	w.Header().Set("Content-Type", "application/problem+json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(responseStatus)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"type": "about:blank", "title": http.StatusText(responseStatus), "status": responseStatus,
		"detail": message, "code": code, "request_id": r.Header.Get("X-Request-ID"),
	})
}
