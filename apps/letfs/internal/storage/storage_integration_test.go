//go:build integration

package storage

import (
	"bytes"
	"crypto/md5"
	"encoding/base64"
	"fmt"
	"io"
	"net/http"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"openlet/apps/letfs/internal/testfixture"
)

func TestIntegrationSignedTransfersAndControl(t *testing.T) {
	endpoint := testfixture.S3(t)
	client, err := New(Config{Endpoint: endpoint, Region: "us-east-1", Bucket: "openlet-integration", AccessKey: "integration", SecretKey: "isolated-testcontainers-secret", AllowHTTP: true})
	require.NoError(t, err)
	httpClient := &http.Client{Timeout: 10 * time.Second}
	request := func(method, target string, headers map[string]string, data []byte) (int, http.Header, []byte) {
		t.Helper()
		req, err := http.NewRequestWithContext(t.Context(), method, target, bytes.NewReader(data))
		require.NoError(t, err)
		for name, value := range headers {
			req.Header.Set(name, value)
		}
		response, err := httpClient.Do(req)
		require.NoError(t, err)
		body, err := io.ReadAll(response.Body)
		require.NoError(t, response.Body.Close())
		require.NoError(t, err)
		return response.StatusCode, response.Header, body
	}
	data := []byte{0, 255, 1, 2, 3, 4}
	for i, tiny := range [][]byte{{1}, {9}, {}, {9, 8}} {
		digest := md5.Sum(tiny)
		key := fmt.Sprintf("candidate/tiny-%d", i)
		capability, err := client.SignPut(t.Context(), key, int64(len(tiny)), base64.StdEncoding.EncodeToString(digest[:]), time.Minute)
		require.NoError(t, err)
		code, _, _ := request(http.MethodPut, capability.URL, capability.Headers, tiny)
		require.Equal(t, http.StatusOK, code)
	}
	digest := md5.Sum(data)
	put, err := client.SignPut(t.Context(), "candidate/a b+?.bin", int64(len(data)), base64.StdEncoding.EncodeToString(digest[:]), time.Minute)
	require.NoError(t, err)
	code, _, _ := request(http.MethodPut, put.URL, put.Headers, data)
	require.Equal(t, http.StatusOK, code)
	code, _, _ = request(http.MethodPut, put.URL, put.Headers, data)
	require.Equal(t, http.StatusPreconditionFailed, code, "candidate is immutable")
	object, err := client.Head(t.Context(), "candidate/a b+?.bin")
	require.NoError(t, err)
	require.EqualValues(t, len(data), object.Size)
	require.NotEmpty(t, object.ETag)
	reader, err := client.Open(t.Context(), "candidate/a b+?.bin")
	require.NoError(t, err)
	content, err := io.ReadAll(reader)
	require.NoError(t, reader.Close())
	require.NoError(t, err)
	require.Equal(t, data, content)
	require.NoError(t, client.Copy(t.Context(), "candidate/a b+?.bin", "copy/file"))
	download, err := client.DownloadURL(t.Context(), "copy/file", "Báo cáo.pdf", time.Minute)
	require.NoError(t, err)
	code, headers, content := request(http.MethodGet, download, map[string]string{"Range": "bytes=1-3"}, nil)
	require.Equal(t, http.StatusPartialContent, code)
	require.Equal(t, data[1:4], content)
	require.Equal(t, "bytes 1-3/6", headers.Get("Content-Range"))
	require.Equal(t, "application/octet-stream", headers.Get("Content-Type"))
	require.Equal(t, "private, no-store", headers.Get("Cache-Control"))
	require.Contains(t, headers.Get("Content-Disposition"), "B%C3%A1o%20c%C3%A1o.pdf")
	code, _, _ = request(http.MethodGet, endpoint+"/openlet-integration/copy/file", nil, nil)
	require.Equal(t, http.StatusForbidden, code)
	require.NoError(t, client.Delete(t.Context(), "copy/file"))
	_, err = client.Head(t.Context(), "copy/file")
	require.ErrorIs(t, err, ErrNotFound)
	require.NoError(t, client.Delete(t.Context(), "copy/file"), "delete replay is idempotent")

	badChecksum, err := client.SignPut(t.Context(), "candidate/bad", int64(len(data)), base64.StdEncoding.EncodeToString(make([]byte, 16)), time.Minute)
	require.NoError(t, err)
	code, _, _ = request(http.MethodPut, badChecksum.URL, badChecksum.Headers, data)
	require.Equal(t, http.StatusBadRequest, code)
	_, err = client.Head(t.Context(), "candidate/bad")
	require.ErrorIs(t, err, ErrNotFound)

	upload, err := client.CreateMultipart(t.Context(), "multipart/file")
	require.NoError(t, err)
	first := bytes.Repeat([]byte{0, 255}, 5*1024*1024/2)
	var receipts []PartReceipt
	for i, partData := range [][]byte{first, data} {
		part, err := client.SignPart(t.Context(), "multipart/file", upload, int32(i+1), int64(len(partData)), time.Minute)
		require.NoError(t, err)
		code, headers, _ := request(http.MethodPut, part.URL, part.Headers, partData)
		require.Equal(t, http.StatusOK, code)
		receipts = append(receipts, PartReceipt{Number: int32(i + 1), ETag: headers.Get("ETag")})
	}
	require.NoError(t, client.CompleteMultipart(t.Context(), "multipart/file", upload, receipts))
	object, err = client.Head(t.Context(), "multipart/file")
	require.NoError(t, err)
	require.EqualValues(t, len(first)+len(data), object.Size)
	reader, err = client.Open(t.Context(), "multipart/file")
	require.NoError(t, err)
	content, err = io.ReadAll(reader)
	require.NoError(t, reader.Close())
	require.NoError(t, err)
	require.Equal(t, append(first, data...), content)
	aborted, err := client.CreateMultipart(t.Context(), "multipart/aborted")
	require.NoError(t, err)
	require.NoError(t, client.AbortMultipart(t.Context(), "multipart/aborted", aborted))
	require.NoError(t, client.AbortMultipart(t.Context(), "multipart/aborted", aborted))
	_, err = client.Head(t.Context(), "multipart/aborted")
	require.ErrorIs(t, err, ErrNotFound)
}

func TestIntegrationProviderSmokeContract(t *testing.T) {
	endpoint := testfixture.S3(t)
	config := Config{Endpoint: endpoint, Region: "us-east-1", Bucket: "openlet-integration", AccessKey: "integration", SecretKey: "isolated-testcontainers-secret", AllowHTTP: true}
	require.EqualError(t, ProviderSmoke(t.Context(), config), "provider smoke requires external HTTPS storage")
	client, err := New(config)
	require.NoError(t, err)
	require.NoError(t, client.smoke(t.Context(), endpoint))
}
