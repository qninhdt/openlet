package http

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"go.temporal.io/sdk/client"
	"log/slog"
	"net/http"
	"openlet/services/user/internal/clerk"
	"openlet/services/user/internal/config"
	"openlet/services/user/internal/user"
	"time"
)

type Server struct {
	Config   config.Config
	DB       *pgxpool.Pool
	Temporal client.Client
	Store    *user.Store
	Clerk    clerk.Client
}

func (s *Server) Router() http.Handler {
	r := chi.NewRouter()
	r.Use(middleware.RequestID, middleware.Recoverer, observe)
	r.Get("/live", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(204) })
	r.Get("/ready", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer cancel()
		if s.DB.Ping(ctx) != nil {
			w.WriteHeader(503)
			return
		}
		if _, e := s.Temporal.CheckHealth(ctx, &client.CheckHealthRequest{}); e != nil {
			w.WriteHeader(503)
			return
		}
		w.WriteHeader(204)
	})
	public := chi.NewRouter()
	public.Post("/onboarding", s.onboardingPost)
	public.Get("/onboarding", s.onboardingGet)
	public.Get("/me", s.me)
	public.Patch("/me", s.updateMe)
	public.NotFound(func(w http.ResponseWriter, r *http.Request) { Error(w, r, 404, "NOT_FOUND", "resource not found") })
	r.Mount("/v1", s.Gateway(public))
	internal := chi.NewRouter()
	internal.Post("/user-summaries", s.summaries)
	internal.Get("/users/{id}/verified-emails", s.verifiedEmails)
	r.Mount("/internal/v1", s.internal(internal))
	return r
}
func Error(w http.ResponseWriter, r *http.Request, status int, code, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]string{"code": code, "message": message, "request_id": middleware.GetReqID(r.Context())}})
}
func (s *Server) Gateway(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if len(r.Header.Values("X-Gateway-Token")) != 1 || subtle.ConstantTimeCompare([]byte(r.Header.Get("X-Gateway-Token")), []byte(s.Config.GatewayToken)) != 1 {
			Error(w, r, 401, "UNAUTHENTICATED", "gateway authentication required")
			return
		}
		if len(r.Header.Values("X-Clerk-Sub")) != 1 || r.Header.Get("X-Clerk-Sub") == "" {
			Error(w, r, 401, "UNAUTHENTICATED", "verified subject required")
			return
		}
		if r.URL.Path != "/v1/onboarding" {
			id, e := uuid.Parse(r.Header.Get("X-Openlet-User-ID"))
			if len(r.Header.Values("X-Openlet-User-ID")) != 1 || e != nil || id == uuid.Nil {
				Error(w, r, 401, "ONBOARDING_REQUIRED", "refresh an onboarded session")
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

func observe(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		started := time.Now()
		response := middleware.NewWrapResponseWriter(w, r.ProtoMajor)
		next.ServeHTTP(response, r)
		slog.Info("HTTP request", "request_id", middleware.GetReqID(r.Context()), "method", r.Method, "status", response.Status(), "elapsed_ms", time.Since(started).Milliseconds())
	})
}
