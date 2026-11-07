package http

import (
	"encoding/json"
	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/account/internal/account"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/httpapi"
	"io"
	"net/http"
)

func decode(w http.ResponseWriter, r *http.Request, out any) error {
	d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16384))
	d.DisallowUnknownFields()
	if err := d.Decode(out); err != nil {
		return account.Fault{Code: "VALIDATION"}
	}
	var extra any
	if d.Decode(&extra) != io.EOF {
		return account.Fault{Code: "VALIDATION"}
	}
	return nil
}
func respond(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
func failure(w http.ResponseWriter, r *http.Request, err error) {
	if _, ok := apperr.As(err); !ok {
		err = apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "dependency unavailable")
	}
	httpapi.WriteError(w, r, err)
}
func identityID(r *http.Request) uuid.UUID {
	return uuid.MustParse(r.Header.Get("X-Openlet-Account-ID"))
}
func writeOnboarding(w http.ResponseWriter, status int, value account.Onboarding) {
	w.Header().Set("Location", "/v1/me/onboarding")
	respond(w, status, value)
}
func (s *Server) onboardingGet(c *gin.Context) {
	value, err := s.Service.GetOnboarding(c.Request.Context(), c.GetHeader("X-Clerk-Sub"))
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	writeOnboarding(c.Writer, http.StatusOK, value)
}
func (s *Server) onboardingPut(c *gin.Context) {
	value, started, err := s.Service.Onboard(c.Request.Context(), c.GetHeader("X-Clerk-Sub"))
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	status := http.StatusOK
	if started {
		status = http.StatusAccepted
	}
	writeOnboarding(c.Writer, status, value)
}
func (s *Server) me(c *gin.Context) {
	value, err := s.Service.Profile(c.Request.Context(), identityID(c.Request))
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	respond(c.Writer, http.StatusOK, value)
}
func (s *Server) updateMe(c *gin.Context) {
	var in struct {
		Name   *string `json:"display_name"`
		Avatar *string `json:"avatar_url"`
	}
	if err := decode(c.Writer, c.Request, &in); err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	value, err := s.Service.UpdateProfile(c.Request.Context(), identityID(c.Request), in.Name, in.Avatar)
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	respond(c.Writer, http.StatusOK, value)
}

func (s *Server) createAccount(c *gin.Context) {
	var in struct {
		Name   string `json:"display_name"`
		Avatar string `json:"avatar_url"`
	}
	if err := decode(c.Writer, c.Request, &in); err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	value, err := s.Service.CreateManaged(c.Request.Context(), identityID(c.Request), in.Name, in.Avatar)
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	respond(c.Writer, http.StatusCreated, value)
}
func (s *Server) getAccount(c *gin.Context) {
	id, err := uuid.Parse(c.Param("id"))
	if err != nil || id == uuid.Nil {
		failure(c.Writer, c.Request, account.Fault{Code: "VALIDATION"})
		return
	}
	value, err := s.Service.GetAccount(c.Request.Context(), identityID(c.Request), id)
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	respond(c.Writer, http.StatusOK, value)
}
func (s *Server) updateAccount(c *gin.Context) {
	id, err := uuid.Parse(c.Param("id"))
	if err != nil || id == uuid.Nil {
		failure(c.Writer, c.Request, account.Fault{Code: "VALIDATION"})
		return
	}
	var in struct {
		Name   *string `json:"display_name"`
		Avatar *string `json:"avatar_url"`
	}
	if err := decode(c.Writer, c.Request, &in); err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	value, err := s.Service.UpdateAccount(c.Request.Context(), identityID(c.Request), id, in.Name, in.Avatar)
	if err != nil {
		failure(c.Writer, c.Request, err)
		return
	}
	respond(c.Writer, http.StatusOK, value)
}
