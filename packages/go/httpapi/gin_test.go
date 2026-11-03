package httpapi

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func TestObserveNormalizesRequestIdentityAndRecoversSafely(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	router.Use(Observe)
	router.GET("/panic", func(c *gin.Context) { panic("password=secret") })
	router.GET("/abort", func(c *gin.Context) { panic(http.ErrAbortHandler) })
	request := httptest.NewRequest("GET", "/panic", nil)
	request.Header.Add("X-Request-ID", "untrusted")
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	require.Equal(t, 500, response.Code)
	require.NotContains(t, response.Body.String(), "secret")
	id, err := uuid.Parse(response.Header().Get("X-Request-ID"))
	require.NoError(t, err)
	require.NotEqual(t, uuid.Nil, id)
	require.Contains(t, response.Body.String(), id.String())
	require.PanicsWithValue(t, http.ErrAbortHandler, func() { router.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest("GET", "/abort", nil)) })
}
