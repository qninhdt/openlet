package http

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/qninhdt/openlet/apps/account/internal/config"
	"github.com/qninhdt/openlet/apps/account/internal/user"
	"github.com/qninhdt/openlet/packages/go/httpapi"
	"github.com/qninhdt/openlet/packages/go/identity"
	"go.opentelemetry.io/contrib/instrumentation/github.com/gin-gonic/gin/otelgin"
	"go.opentelemetry.io/otel/propagation"
)

type Server struct {
	Config  config.Config
	Service *user.Service
	Ready   func(context.Context) error
}

func (s *Server) Router() *gin.Engine {
	r := gin.New()
	r.RedirectTrailingSlash = false
	r.RedirectFixedPath = false
	// Identity comes from authenticated gateway headers, never forwarded IP headers.
	_ = r.SetTrustedProxies(nil)
	r.Use(otelgin.Middleware("openlet-account", otelgin.WithPropagators(propagation.TraceContext{})), httpapi.Observe)
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
		if s.Ready == nil || s.Ready(ctx) != nil {
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

var Error = httpapi.Problem

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
