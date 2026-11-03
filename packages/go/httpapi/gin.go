package httpapi

import (
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"log/slog"
	"net/http"
	"time"
)

func Observe(c *gin.Context) {
	requestID, err := uuid.Parse(c.GetHeader("X-Request-ID"))
	if len(c.Request.Header.Values("X-Request-ID")) != 1 || err != nil || requestID == uuid.Nil {
		requestID = uuid.New()
	}
	c.Request.Header.Set("X-Request-ID", requestID.String())
	c.Header("X-Request-ID", requestID.String())
	started := time.Now()
	defer func() {
		if recovered := recover(); recovered != nil {
			if recovered == http.ErrAbortHandler {
				panic(recovered)
			}
			slog.ErrorContext(c.Request.Context(), "HTTP handler panic", "request_id", requestID.String())
			if !c.Writer.Written() {
				Problem(c.Writer, c.Request, 500, "INTERNAL", "internal server error")
			}
			c.Abort()
		}
		slog.InfoContext(c.Request.Context(), "HTTP request", "request_id", requestID.String(), "method", c.Request.Method, "route", c.FullPath(), "status", c.Writer.Status(), "elapsed_ms", time.Since(started).Milliseconds())
	}()
	c.Next()
}
