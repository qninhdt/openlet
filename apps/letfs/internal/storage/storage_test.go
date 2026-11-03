package storage

import (
	"context"
	"encoding/base64"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
)

func testConfig(endpoint string) Config {
	return Config{Endpoint: endpoint, Region: "us-east-1", Bucket: "isolated", AccessKey: "test-access", SecretKey: "isolated-test-secret", AllowHTTP: true}
}

func TestSigningEndpointsAndBoundHeaders(t *testing.T) {
	config := testConfig("http://internal.invalid:8333")
	config.SigningEndpoint = "https://browser.invalid"
	client, err := New(config)
	require.NoError(t, err)
	checksum := base64.StdEncoding.EncodeToString(make([]byte, 16))
	upload, err := client.SignPut(t.Context(), "candidates/a b+?.bin", 12, checksum, time.Minute)
	require.NoError(t, err)
	target, err := url.Parse(upload.URL)
	require.NoError(t, err)
	require.Equal(t, "browser.invalid", target.Host)
	require.Equal(t, "/isolated/candidates/a b+?.bin", target.Path)
	require.Equal(t, "content-length;content-md5;host;if-none-match", target.Query().Get("X-Amz-SignedHeaders"))
	require.Equal(t, "60", target.Query().Get("X-Amz-Expires"))
	require.Equal(t, map[string]string{"content-md5": checksum, "if-none-match": "*"}, upload.Headers)
	require.EqualValues(t, 12, upload.ContentLength)
	require.WithinDuration(t, time.Now().Add(time.Minute), upload.ExpiresAt, 2*time.Second)
	part, err := client.SignPart(t.Context(), "multipart", "opaque/+ id", 2, 7, time.Minute)
	require.NoError(t, err)
	partURL, err := url.Parse(part.URL)
	require.NoError(t, err)
	require.Equal(t, "2", partURL.Query().Get("partNumber"))
	require.Equal(t, "opaque/+ id", partURL.Query().Get("uploadId"))
	require.Equal(t, "content-length;host", partURL.Query().Get("X-Amz-SignedHeaders"))
	processorUpload, err := client.ProcessorSignPut(t.Context(), "outputs/text.md", 12, checksum, time.Minute)
	require.NoError(t, err)
	processorURL, err := url.Parse(processorUpload.URL)
	require.NoError(t, err)
	require.Equal(t, "internal.invalid:8333", processorURL.Host)
	require.Equal(t, upload.Headers, processorUpload.Headers)
	processorPart, err := client.ProcessorSignPart(t.Context(), "multipart", "opaque/+ id", 2, 7, time.Minute)
	require.NoError(t, err)
	processorURL, err = url.Parse(processorPart.URL)
	require.NoError(t, err)
	require.Equal(t, "internal.invalid:8333", processorURL.Host)
	require.Equal(t, "opaque/+ id", processorURL.Query().Get("uploadId"))
	for _, internal := range []bool{false, true} {
		var signed string
		if internal {
			signed, err = client.ProcessorDownloadURL(t.Context(), "objects/key", "Báo cáo \"\r\n.pdf", time.Minute)
		} else {
			signed, err = client.DownloadURL(t.Context(), "objects/key", "Báo cáo \"\r\n.pdf", time.Minute)
		}
		require.NoError(t, err)
		target, err := url.Parse(signed)
		require.NoError(t, err)
		expectedHost := "browser.invalid"
		if internal {
			expectedHost = "internal.invalid:8333"
		}
		require.Equal(t, expectedHost, target.Host)
		require.Equal(t, "application/octet-stream", target.Query().Get("response-content-type"))
		require.Equal(t, "private, no-store", target.Query().Get("response-cache-control"))
		require.Equal(t, `attachment; filename="download"; filename*=UTF-8''B%C3%A1o%20c%C3%A1o%20%22%0D%0A.pdf`, target.Query().Get("response-content-disposition"))
	}
}

func TestStorageInputValidation(t *testing.T) {
	for _, endpoint := range []string{"http://insecure.invalid", "ftp://wrong.invalid", "https://user:password@host", "https://host?token=secret", "https://host#fragment", "https://host?", "missing-host"} {
		config := testConfig(endpoint)
		config.AllowHTTP = false
		_, err := New(config)
		require.Error(t, err)
		require.NotContains(t, err.Error(), "secret")
	}
	client, err := New(testConfig("http://local.invalid"))
	require.NoError(t, err)
	checksum := base64.StdEncoding.EncodeToString(make([]byte, 16))
	for _, key := range []string{"", "a\x00b", strings.Repeat("k", 1025), string([]byte{255})} {
		_, err := client.SignPut(t.Context(), key, 1, checksum, time.Minute)
		require.ErrorIs(t, err, ErrInvalid)
		_, err = client.Head(t.Context(), key)
		require.ErrorIs(t, err, ErrInvalid)
	}
	for _, digest := range []string{"", "not-base64", base64.StdEncoding.EncodeToString([]byte("short"))} {
		_, err := client.SignPut(t.Context(), "key", 1, digest, time.Minute)
		require.ErrorIs(t, err, ErrInvalid)
	}
	for _, lifetime := range []time.Duration{0, time.Millisecond, time.Hour + time.Second} {
		_, err := client.SignPut(t.Context(), "key", 1, checksum, lifetime)
		require.ErrorIs(t, err, ErrInvalid)
	}
	_, err = client.DownloadURL(t.Context(), "key", "file", 11*time.Minute)
	require.ErrorIs(t, err, ErrInvalid)
	for _, receipts := range [][]PartReceipt{nil, {{Number: 2, ETag: "etag"}}, {{Number: 1, ETag: ""}}, {{Number: 1, ETag: "a\r\nb"}}} {
		require.ErrorIs(t, client.CompleteMultipart(t.Context(), "key", "upload", receipts), ErrInvalid)
	}
	_, err = client.SignPart(t.Context(), "key", "upload", 10001, 1, time.Minute)
	require.ErrorIs(t, err, ErrInvalid)
	_, err = client.SignPut(t.Context(), "key", -1, checksum, time.Minute)
	require.ErrorIs(t, err, ErrInvalid)
}

func TestControlFailuresNeverRetryOrExposeProviderBody(t *testing.T) {
	for _, mode := range []string{"unavailable", "lost-response", "embedded-completion-error"} {
		t.Run(mode, func(t *testing.T) {
			var attempts atomic.Int32
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				attempts.Add(1)
				_, _ = io.Copy(io.Discard, r.Body)
				if mode == "lost-response" {
					conn, _, err := w.(http.Hijacker).Hijack()
					if err == nil {
						_ = conn.Close()
					}
					return
				}
				w.Header().Set("Content-Type", "application/xml")
				if mode != "embedded-completion-error" {
					w.WriteHeader(http.StatusServiceUnavailable)
				}
				_, _ = io.WriteString(w, `<Error><Code>InternalError</Code><Message>secret-provider-diagnostic</Message></Error>`)
			}))
			t.Cleanup(server.Close)
			client, err := New(testConfig(server.URL))
			require.NoError(t, err)
			if mode == "embedded-completion-error" {
				err = client.CompleteMultipart(t.Context(), "key", "upload", []PartReceipt{{Number: 1, ETag: `"etag"`}})
			} else {
				err = client.Copy(t.Context(), "source", "destination")
			}
			require.ErrorIs(t, err, ErrUnavailable)
			require.EqualValues(t, 1, attempts.Load(), "one durable invocation has one wire attempt")
			require.NotContains(t, err.Error(), "secret-provider")
		})
	}
}

func TestControlErrorClassificationAndCancellation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/missing") {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		w.Header().Set("Content-Type", "application/xml")
		w.WriteHeader(http.StatusPreconditionFailed)
		_, _ = io.WriteString(w, `<Error><Code>PreconditionFailed</Code></Error>`)
	}))
	t.Cleanup(server.Close)
	client, err := New(testConfig(server.URL))
	require.NoError(t, err)
	_, err = client.Head(t.Context(), "missing")
	require.ErrorIs(t, err, ErrNotFound)
	require.ErrorIs(t, client.Copy(t.Context(), "source", "destination"), ErrPrecondition)
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	err = client.Delete(ctx, "key")
	require.True(t, errors.Is(err, context.Canceled))
}
