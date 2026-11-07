// Package httpapi provides public HTTP protocol helpers, without RPC dependencies.
package httpapi

import (
	"encoding/json"

	"github.com/qninhdt/openlet/packages/go/apperr"
	"net/http"
)

func Problem(w http.ResponseWriter, r *http.Request, status int, code, message string) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"type": "about:blank", "title": http.StatusText(status), "status": status,
		"detail": message, "code": code, "request_id": r.Header.Get("X-Request-ID"),
	})
}
func WriteError(w http.ResponseWriter, r *http.Request, err error) {
	fault := apperr.Safe(err)
	status := http.StatusInternalServerError
	switch fault.Kind {
	case apperr.Invalid, apperr.OutOfRange:
		status = 400
	case apperr.Unauthenticated:
		status = 401
	case apperr.Forbidden:
		status = 403
	case apperr.Missing:
		status = 404
	case apperr.Exists, apperr.Conflict:
		status = 409
	case apperr.Precondition:
		status = 400
	case apperr.Limit:
		status = 429
	case apperr.Unavailable:
		status = 503
	case apperr.Canceled:
		status = 499
	case apperr.Timeout:
		status = 504
	case apperr.Unsupported:
		status = 501
	}
	switch fault.Reason {
	case "PRECONDITION_REQUIRED":
		status = 428
	case "REVISION_MISMATCH", "TARGET_MISMATCH":
		status = 412
	case "REQUEST_LIMIT":
		status = 413
	case "INVALID_RANGE":
		status = 416
	}
	Problem(w, r, status, fault.Reason, fault.Message)
}
