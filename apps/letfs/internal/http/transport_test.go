package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/rpc"
)

func TestDownloadHTTPContract(t *testing.T) {
	payload := []byte{0, 255, 128, '\r', '\n', '<', 'x', '>', 0, 1}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		download := &letfsv1.Download{Etag: `"7"`, Mime: "text/html", SizeBytes: int64(len(payload)), Source: &letfsv1.Download_InlineContent{InlineContent: payload}}
		if r.URL.Path == "/empty" {
			download.SizeBytes = 0
			download.Source = &letfsv1.Download_InlineContent{InlineContent: []byte{}}
		}
		if r.URL.Path == "/object" {
			download.Source = &letfsv1.Download_SignedUrl{SignedUrl: "https://objects.example.test/file?signed=opaque"}
		}
		if err := writeDownload(w, r, download); err != nil {
			rpc.WriteHTTPError(w, r, err)
		}
	}))
	t.Cleanup(server.Close)
	client := server.Client()
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	for _, test := range []struct {
		name, path string
		ranges     []string
		status     int
		want       []byte
		code       string
	}{
		{"exact", "/", nil, 200, payload, ""},
		{"single", "/", []string{"bytes=1-3"}, 206, payload[1:4], ""},
		{"suffix", "/", []string{"bytes=-2"}, 206, payload[8:], ""},
		{"open ended", "/", []string{"bytes=8-"}, 206, payload[8:], ""},
		{"clamped", "/", []string{"bytes=8-999"}, 206, payload[8:], ""},
		{"large suffix", "/", []string{"bytes=-18446744073709551615"}, 206, payload, ""},
		{"empty", "/empty", nil, 200, []byte{}, ""},
		{"empty range", "/empty", []string{"bytes=0-0"}, 416, nil, "INVALID_RANGE"},
		{"empty header", "/", []string{""}, 416, nil, "INVALID_RANGE"},
		{"duplicate", "/", []string{"bytes=0-1", "bytes=3-4"}, 416, nil, "INVALID_RANGE"},
		{"multiple", "/", []string{"bytes=0-1,3-4"}, 416, nil, "INVALID_RANGE"},
		{"unsatisfied", "/", []string{"bytes=100-"}, 416, nil, "INVALID_RANGE"},
		{"negative zero", "/", []string{"bytes=-0"}, 416, nil, "INVALID_RANGE"},
		{"plus", "/", []string{"bytes=+1-3"}, 416, nil, "INVALID_RANGE"},
		{"backwards", "/", []string{"bytes=3-1"}, 416, nil, "INVALID_RANGE"},
		{"overflow", "/", []string{"bytes=18446744073709551616-"}, 416, nil, "INVALID_RANGE"},
		{"wrong unit", "/", []string{"items=0-1"}, 416, nil, "INVALID_RANGE"},
		{"whitespace", "/", []string{"bytes= 0-1"}, 416, nil, "INVALID_RANGE"},
		{"revision", "/?revision=6", nil, 412, nil, "REVISION_MISMATCH"},
		{"duplicate revision", "/?revision=7&revision=7", nil, 400, nil, "VALIDATION"},
		{"empty revision", "/?revision=", nil, 400, nil, "VALIDATION"},
		{"object", "/object", nil, 307, nil, ""},
		{"invalid object range", "/object", []string{"invalid"}, 416, nil, "INVALID_RANGE"},
	} {
		t.Run(test.name, func(t *testing.T) {
			r, err := http.NewRequestWithContext(t.Context(), "GET", server.URL+test.path, nil)
			require.NoError(t, err)
			for _, value := range test.ranges {
				r.Header.Add("Range", value)
			}
			response, err := client.Do(r)
			require.NoError(t, err)
			defer response.Body.Close()
			body, err := io.ReadAll(response.Body)
			require.NoError(t, err)
			require.Equal(t, test.status, response.StatusCode)
			if test.code != "" {
				require.Equal(t, "application/problem+json", response.Header.Get("Content-Type"))
				var problem map[string]any
				require.NoError(t, json.Unmarshal(body, &problem))
				require.Equal(t, test.code, problem["code"])
			} else if test.status == 307 {
				require.Equal(t, "https://objects.example.test/file?signed=opaque", response.Header.Get("Location"))
				require.Empty(t, body)
			} else {
				require.Equal(t, test.want, body)
				require.Equal(t, "text/html", response.Header.Get("Content-Type"))
				require.Equal(t, "attachment", response.Header.Get("Content-Disposition"))
				require.Equal(t, "nosniff", response.Header.Get("X-Content-Type-Options"))
				require.Equal(t, `"7"`, response.Header.Get("ETag"))
				require.Equal(t, "bytes", response.Header.Get("Accept-Ranges"))
			}
		})
	}
}

func TestBoundedJSONPreconditionsAndMutationResponse(t *testing.T) {
	for _, test := range []struct {
		name, body string
		length     int64
		status     int
	}{
		{"valid", `{"name":"ok"}`, -1, 201},
		{"unknown", `{"unknown":true}`, -1, 400},
		{"multiple", `{"name":"ok"}{}`, -1, 400},
		{"empty", "", 0, 400},
		{"declared oversize", `{}`, maxJSONBody + 1, 413},
		{"stream oversize", `{"name":"ok"}` + strings.Repeat(" ", maxJSONBody), -1, 413},
	} {
		t.Run(test.name, func(t *testing.T) {
			r := httptest.NewRequest("POST", "/v1/filesystems/drive/nodes", strings.NewReader(test.body))
			r.ContentLength = test.length
			w := httptest.NewRecorder()
			var input struct {
				Name string `json:"name"`
			}
			if err := decodeJSON(w, r, &input); err != nil {
				rpc.WriteHTTPError(w, r, err)
			} else {
				writeProto(w, r, 201, "/v1/filesystems/drive/nodes/node", `"1"`, &letfsv1.Node{Id: "node", Revision: 1, Name: input.Name})
			}
			require.Equal(t, test.status, w.Code)
			if test.status == 201 {
				require.Equal(t, "/v1/filesystems/drive/nodes/node", w.Header().Get("Location"))
				require.Equal(t, `"1"`, w.Header().Get("ETag"))
				require.Contains(t, w.Body.String(), `"revision":"1"`)
			} else if test.status == 413 {
				require.Contains(t, w.Body.String(), `"code":"REQUEST_LIMIT"`)
			}
		})
	}
	for _, test := range []struct {
		values []string
		status int
	}{
		{nil, 428}, {[]string{`"7"`}, 202}, {[]string{`"9223372036854775807"`}, 202},
		{[]string{""}, 400}, {[]string{`W/"7"`}, 400}, {[]string{`"07"`}, 400}, {[]string{`"0"`}, 400},
		{[]string{`"7"`, `"7"`}, 400}, {[]string{`"9223372036854775808"`}, 400},
	} {
		r := httptest.NewRequest("PATCH", "/", nil)
		for _, value := range test.values {
			r.Header.Add("If-Match", value)
		}
		w := httptest.NewRecorder()
		if _, err := requiredRevision(r); err != nil {
			rpc.WriteHTTPError(w, r, err)
		} else {
			writeProto(w, r, 202, "/v1/filesystems/drive/copies/copy", `"8"`, &letfsv1.Node{Revision: 8})
		}
		require.Equal(t, test.status, w.Code)
		if test.status == 202 {
			require.Equal(t, "/v1/filesystems/drive/copies/copy", w.Header().Get("Location"))
		}
	}
	r := httptest.NewRequest("GET", "/", nil)
	w := httptest.NewRecorder()
	writeProto(w, r, 201, "//foreign.test/path", "", &letfsv1.Node{})
	require.Equal(t, 500, w.Code)
	require.Empty(t, w.Header().Get("Location"))
	require.False(t, bytes.Contains(w.Body.Bytes(), []byte("foreign.test")))
}
