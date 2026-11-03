package http

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strings"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin"
	"go.opentelemetry.io/otel/propagation"
	"go.temporal.io/sdk/client"
	"openlet/apps/account/internal/clerk"
	"openlet/apps/account/internal/config"
	"openlet/apps/account/internal/user"
	"openlet/packages/go/identity"
)

type Server struct {
	Graph      v1.PermissionsServiceClient
	GraphReady func(context.Context) error
	Config     config.Config
	DB         *pgxpool.Pool
	Temporal   client.Client
	Store      *user.Store
	Clerk      clerk.Client
}

func (s *Server) Router() *gin.Engine {
	r := gin.New()
	r.RedirectTrailingSlash = false
	r.RedirectFixedPath = false
	// Identity comes from authenticated gateway headers, never forwarded IP headers.
	_ = r.SetTrustedProxies(nil)
	r.Use(otelgin.Middleware("openlet-account", otelgin.WithPropagators(propagation.TraceContext{})), observe)
	r.Use(func(c *gin.Context) {
		path := c.Request.URL.Path
		if path == "/v1" || strings.HasPrefix(path, "/v1/") {
			s.Gateway(c)
		}
	})
	r.GET("/live", func(c *gin.Context) { c.Status(http.StatusNoContent) })
	r.GET("/ready", func(c *gin.Context) {
		ctx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
		defer cancel()
		if s.GraphReady == nil || s.GraphReady(ctx) != nil || s.DB.Ping(ctx) != nil {
			c.Status(http.StatusServiceUnavailable)
			return
		}
		if _, err := s.Temporal.CheckHealth(ctx, &client.CheckHealthRequest{}); err != nil {
			c.Status(http.StatusServiceUnavailable)
			return
		}
		c.Status(http.StatusNoContent)
	})
	public := r.Group("/v1")

	public.PUT("/me/onboarding", s.onboardingPut)
	public.GET("/me/onboarding", s.onboardingGet)
	public.GET("/me", s.me)
	public.PATCH("/me", s.updateMe)
	r.NoRoute(func(c *gin.Context) {
		Error(c.Writer, c.Request, 404, "NOT_FOUND", "resource not found")
	})
	return r
}

func Error(w http.ResponseWriter, r *http.Request, status int, code, message string) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"type": "about:blank", "title": http.StatusText(status), "status": status, "detail": message, "code": code, "request_id": r.Header.Get("X-Request-ID")})
}

func (s *Server) Gateway(c *gin.Context) {
	r := c.Request
	bootstrap := r.URL.Path == "/v1/me/onboarding" && (r.Method == http.MethodGet || r.Method == http.MethodPut)
	principal, err := identity.AuthenticateGateway(r.Header, s.Config.GatewayToken, bootstrap)
	if err != nil {
		code := "UNAUTHENTICATED"
		if errors.Is(err, identity.ErrOnboardingRequired) {
			code = "ONBOARDING_REQUIRED"
		}
		Error(c.Writer, r, http.StatusUnauthorized, code, err.Error())
		c.Abort()
		return
	}
	c.Request = r.WithContext(identity.WithPrincipal(r.Context(), principal))
}

func observe(c *gin.Context) {
	requestID, err := uuid.Parse(c.GetHeader("X-Request-ID"))
	if len(c.Request.Header.Values("X-Request-ID")) != 1 || err != nil || requestID == uuid.Nil {
		requestID = uuid.New()
	}
	c.Request.Header.Set("X-Request-ID", requestID.String())
	c.Header("X-Request-ID", requestID.String())
	started := time.Now()
	defer func() {
		if recover() != nil {
			slog.ErrorContext(c.Request.Context(), "HTTP handler panic", "request_id", requestID.String())
			if !c.Writer.Written() {
				Error(c.Writer, c.Request, 500, "INTERNAL", "internal server error")
			}
			c.Abort()
		}
		slog.InfoContext(c.Request.Context(), "HTTP request", "request_id", requestID.String(), "method", c.Request.Method, "route", c.FullPath(), "status", c.Writer.Status(), "elapsed_ms", time.Since(started).Milliseconds())
	}()
	c.Next()
}
