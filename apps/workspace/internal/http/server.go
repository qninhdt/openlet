package http

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin"
	"go.opentelemetry.io/otel/propagation"
	"go.temporal.io/sdk/client"
	"openlet/apps/workspace/internal/config"
	"openlet/apps/workspace/internal/user"
	"openlet/apps/workspace/internal/workspace"
)

type Server struct {
	Config   config.Config
	DB       *pgxpool.Pool
	Temporal client.Client
	Store    *workspace.Store
	User     user.Client
}

func (s *Server) Router() *gin.Engine {
	r := gin.New()
	r.RedirectTrailingSlash = false
	r.RedirectFixedPath = false
	// Identity comes from authenticated gateway headers, never forwarded IP headers.
	_ = r.SetTrustedProxies(nil)
	r.Use(otelgin.Middleware("openlet-workspace", otelgin.WithPropagators(propagation.TraceContext{})), observe)
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
		if s.DB.Ping(ctx) != nil {
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

	registerFiles(public, s)
	public.POST("/workspaces", s.createWorkspace)
	public.GET("/workspaces", s.listWorkspaces)
	public.GET("/workspaces/:ws", s.getWorkspace)
	public.PATCH("/workspaces/:ws", s.updateWorkspace)
	public.DELETE("/workspaces/:ws", s.deleteWorkspace)
	public.GET("/workspaces/:ws/members", s.members)
	public.PATCH("/workspaces/:ws/members/:user", s.changeMember)
	public.DELETE("/workspaces/:ws/members/:user", s.changeMember)
	public.POST("/workspaces/:ws/invitations", s.invite)
	public.GET("/workspaces/:ws/invitations", s.invitations)
	public.DELETE("/workspaces/:ws/invitations/:invitation", s.revokeInvitation)
	public.POST("/memberships", s.acceptInvitation)
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
	if len(r.Header.Values("X-Gateway-Token")) != 1 || subtle.ConstantTimeCompare([]byte(r.Header.Get("X-Gateway-Token")), []byte(s.Config.GatewayToken)) != 1 {
		Error(c.Writer, r, 401, "UNAUTHENTICATED", "gateway authentication required")
		c.Abort()
		return
	}
	if len(r.Header.Values("X-Clerk-Sub")) != 1 || r.Header.Get("X-Clerk-Sub") == "" {
		Error(c.Writer, r, 401, "UNAUTHENTICATED", "verified subject required")
		c.Abort()
		return
	}
	id, err := uuid.Parse(r.Header.Get("X-Openlet-User-ID"))
	if len(r.Header.Values("X-Openlet-User-ID")) != 1 || err != nil || id == uuid.Nil {
		Error(c.Writer, r, 401, "ONBOARDING_REQUIRED", "refresh an onboarded session")
		c.Abort()
	}

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
		if recovered := recover(); recovered != nil {
			if recovered == http.ErrAbortHandler {
				panic(recovered)
			}
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
