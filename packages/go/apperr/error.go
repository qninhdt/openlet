// Package apperr defines safe application failures independently of any transport.
package apperr

import (
	"context"
	"errors"
)

type Kind uint8

const (
	None Kind = iota
	Internal
	Invalid
	Unauthenticated
	Forbidden
	Missing
	Exists
	Conflict
	Precondition
	Limit
	Unavailable
	Canceled
	Timeout
	Unsupported
	OutOfRange
)

type Error struct {
	Kind    Kind
	Reason  string
	Message string
}

func (e *Error) Error() string                    { return e.Message }
func New(kind Kind, reason, message string) error { return &Error{kind, reason, message} }
func As(err error) (*Error, bool) {
	var fault *Error
	ok := errors.As(err, &fault)
	return fault, ok
}
func KindOf(err error) Kind {
	if err == nil {
		return None
	}
	if errors.Is(err, context.Canceled) {
		return Canceled
	}
	if errors.Is(err, context.DeadlineExceeded) {
		return Timeout
	}
	if fault, ok := As(err); ok {
		return fault.Kind
	}
	return Internal
}
func Safe(err error) *Error {
	if fault, ok := As(err); ok {
		return fault
	}
	switch KindOf(err) {
	case Canceled:
		return &Error{Canceled, "CANCELED", "request canceled"}
	case Timeout:
		return &Error{Timeout, "TIMEOUT", "request deadline exceeded"}
	default:
		return &Error{Internal, "INTERNAL", "internal server error"}
	}
}
func Retryable(err error) bool {
	switch KindOf(err) {
	case Invalid, Unauthenticated, Forbidden, Missing, Exists, Conflict, Precondition, Limit, OutOfRange, Unsupported:
		return false
	default:
		return true
	}
}
