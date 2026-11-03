package httpapi

import (
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"testing/iotest"
	"time"

	"github.com/stretchr/testify/require"
)

func TestArchiveHTTPHeadersAndTerminalFailure(t *testing.T) {
	for _, test := range []struct {
		name   string
		reader io.Reader
		abort  bool
	}{
		{"complete", strings.NewReader("archive-bytes"), false},
		{"data with EOF", iotest.DataErrReader(strings.NewReader("archive-bytes")), false},
		{"late failure", io.MultiReader(strings.NewReader("archive-bytes"), iotest.ErrReader(errors.New("stream failed"))), true},
		{"empty", strings.NewReader(""), true},
		{"initial read failure", iotest.ErrReader(errors.New("stream failed")), true},
	} {
		t.Run(test.name, func(t *testing.T) {
			w := httptest.NewRecorder()
			if test.abort {
				require.PanicsWithValue(t, http.ErrAbortHandler, func() { _ = writeArchive(w, time.Now().Add(time.Second), "Báo cáo.zip", test.reader) })
			} else {
				require.NoError(t, writeArchive(w, time.Now().Add(time.Second), "Báo cáo.zip", test.reader))
				require.Equal(t, "archive-bytes", w.Body.String())
			}
			require.Equal(t, "application/zip", w.Header().Get("Content-Type"))
			require.Equal(t, "private, no-store", w.Header().Get("Cache-Control"))
			require.Equal(t, "nosniff", w.Header().Get("X-Content-Type-Options"))
			require.Equal(t, `attachment; filename="download.zip"; filename*=UTF-8''B%C3%A1o%20c%C3%A1o.zip`, w.Header().Get("Content-Disposition"))
		})
	}
	for _, name := range []string{"", "bad\r\nheader.zip"} {
		w := httptest.NewRecorder()
		err := writeArchive(w, time.Now().Add(time.Second), name, strings.NewReader("unused"))
		require.Error(t, err)
		require.Empty(t, w.Header().Get("Content-Type"))
	}
}
