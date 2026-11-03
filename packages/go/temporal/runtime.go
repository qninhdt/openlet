// Package temporal translates shared runtime concerns at the workflow boundary.
package temporal

import (
	"github.com/qninhdt/openlet/packages/go/apperr"
	"go.opentelemetry.io/otel/propagation"
	temporalotel "go.temporal.io/sdk/contrib/opentelemetry"
	"go.temporal.io/sdk/interceptor"
	"go.temporal.io/sdk/temporal"
)

func Tracing() (interceptor.Interceptor, error) {
	return temporalotel.NewTracingInterceptor(temporalotel.TracerOptions{DisableBaggage: true, TextMapPropagator: propagation.TraceContext{}})
}

// Error exports only safe failures into durable workflow history.
func Error(err error) error {
	if err == nil {
		return nil
	}
	if apperr.KindOf(err) == apperr.Canceled {
		return temporal.NewCanceledError()
	}
	fault := apperr.Safe(err)
	if !apperr.Retryable(err) {
		return temporal.NewNonRetryableApplicationError(fault.Message, fault.Reason, nil)
	}
	return temporal.NewApplicationError(fault.Message, fault.Reason)
}
