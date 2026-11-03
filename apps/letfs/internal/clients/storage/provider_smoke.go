package storage

import (
	"bytes"
	"context"
	"crypto/md5"
	"encoding/base64"
	"errors"
	"io"
	"maps"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
)

func ProviderSmoke(ctx context.Context, config Config) error {
	if config.AllowHTTP {
		return errors.New("provider smoke requires external HTTPS storage")
	}
	client, err := New(config)
	if err != nil {
		return err
	}
	if config.SigningEndpoint == "" {
		config.SigningEndpoint = config.Endpoint
	}
	return client.smoke(ctx, strings.TrimRight(config.SigningEndpoint, "/"))
}

// The same transfer contract runs against local storage and the selected provider.
func (s *Client) smoke(ctx context.Context, endpoint string) (result error) {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	prefix := "smoke/" + uuid.Must(uuid.NewV7()).String()
	key, copied, multipart := prefix+"/source", prefix+"/copied", prefix+"/multipart"
	var upload string
	defer func() {
		cleanup, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()
		if upload != "" {
			if err := s.AbortMultipart(cleanup, multipart, upload); err != nil && !errors.Is(err, ErrNotFound) {
				result = errors.Join(result, errors.New("multipart cleanup failed"))
			}
		}
		for _, path := range []string{key, copied, multipart} {
			if err := s.Delete(cleanup, path); err != nil {
				result = errors.Join(result, errors.New("object cleanup failed"))
			}
		}
		if _, err := s.Head(cleanup, key); !errors.Is(err, ErrNotFound) {
			result = errors.Join(result, errors.New("deleted key is still readable or unavailable"))
		}
	}()
	client := &http.Client{Timeout: 30 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	request := func(method, target string, headers map[string]string, body []byte) (int, http.Header, []byte, error) {
		req, err := http.NewRequestWithContext(ctx, method, target, bytes.NewReader(body))
		if err != nil {
			return 0, nil, nil, ErrUnavailable
		}
		for name, value := range headers {
			req.Header.Set(name, value)
		}
		response, err := client.Do(req)
		if err != nil {
			return 0, nil, nil, ErrUnavailable
		}
		defer response.Body.Close()
		data, err := io.ReadAll(io.LimitReader(response.Body, 6*1024*1024))
		return response.StatusCode, response.Header, data, providerError(err)
	}
	data := []byte("\x00openlet-provider\xff")
	digest := md5.Sum(data)
	signed, err := s.SignPut(ctx, key, int64(len(data)), base64.StdEncoding.EncodeToString(digest[:]), time.Minute)
	if err != nil {
		return err
	}
	for _, header := range []string{"content-md5", "if-none-match"} {
		for _, altered := range []bool{false, true} {
			headers := maps.Clone(signed.Headers)
			delete(headers, header)
			if altered {
				headers[header] = "AAAAAAAAAAAAAAAAAAAAAA=="
			}
			code, _, _, err := request(http.MethodPut, signed.URL, headers, data)
			if err != nil || code < 400 || code >= 500 {
				return errors.New("provider accepted missing or altered signed header, or request failed")
			}
		}
	}
	for _, wrong := range [][]byte{bytes.Repeat([]byte{'x'}, len(data)), []byte("short")} {
		code, _, _, err := request(http.MethodPut, signed.URL, signed.Headers, wrong)
		if err != nil || code < 400 || code >= 500 {
			return errors.New("provider accepted incorrect checksum or length, or request failed")
		}
	}
	codes := make(chan int, 2)
	for range 2 {
		go func() {
			code, _, _, err := request(http.MethodPut, signed.URL, signed.Headers, data)
			if err != nil {
				code = 0
			}
			codes <- code
		}()
	}
	first, second := <-codes, <-codes
	if first != http.StatusOK {
		first, second = second, first
	}
	if first != http.StatusOK || second != http.StatusConflict && second != http.StatusPreconditionFailed {
		return errors.New("provider did not admit exactly one conditional writer")
	}
	if code, _, _, err := request(http.MethodPut, signed.URL, signed.Headers, data); err != nil || code != http.StatusPreconditionFailed {
		return errors.New("provider did not enforce immutable conditional PUT")
	}
	head, err := s.Head(ctx, key)
	if err != nil || head.Size != int64(len(data)) {
		return errors.New("conditional HEAD mismatch")
	}
	if err := s.Copy(ctx, key, copied); err != nil {
		return err
	}
	reader, err := s.Open(ctx, copied)
	if err != nil {
		return err
	}
	content, readErr := io.ReadAll(io.LimitReader(reader, int64(len(data)+1)))
	closeErr := reader.Close()
	if readErr != nil || closeErr != nil || !bytes.Equal(content, data) {
		return errors.New("provider copy changed bytes")
	}
	download, err := s.DownloadURL(ctx, key, "provider ü.bin", time.Minute)
	if err != nil {
		return err
	}
	code, headers, content, err := request(http.MethodGet, download, map[string]string{"Range": "bytes=1-4"}, nil)
	if err != nil || code != http.StatusPartialContent || headers.Get("Content-Type") != "application/octet-stream" || !strings.Contains(headers.Get("Content-Disposition"), "provider%20%C3%BC.bin") || !bytes.Equal(content, data[1:5]) {
		return errors.New("signed GET range or attachment mismatch")
	}
	if endpoint == "" {
		return errors.New("anonymous endpoint required")
	}
	code, _, _, err = request(http.MethodGet, endpoint+"/"+s.bucket+"/"+key, nil, nil)
	if err != nil || code != http.StatusForbidden && code != http.StatusNotFound {
		return errors.New("anonymous read was not denied")
	}
	upload, err = s.CreateMultipart(ctx, multipart)
	if err != nil {
		return err
	}
	parts := [][]byte{bytes.Repeat([]byte{'a'}, 5*1024*1024), []byte("last part")}
	var receipts []PartReceipt
	for i, part := range parts {
		signed, err := s.SignPart(ctx, multipart, upload, int32(i+1), int64(len(part)), time.Minute)
		if err != nil {
			return err
		}
		code, headers, _, err := request(http.MethodPut, signed.URL, signed.Headers, part)
		if err != nil || code != http.StatusOK {
			return errors.New("signed multipart upload failed")
		}
		receipts = append(receipts, PartReceipt{Number: int32(i + 1), ETag: headers.Get("ETag")})
	}
	if err := s.CompleteMultipart(ctx, multipart, upload, receipts); err != nil {
		return err
	}
	head, err = s.Head(ctx, multipart)
	if err != nil || head.Size != int64(len(parts[0])+len(parts[1])) || head.ETag == "" {
		return errors.New("multipart HEAD mismatch")
	}
	reader, err = s.Open(ctx, multipart)
	if err != nil {
		return err
	}
	content, readErr = io.ReadAll(io.LimitReader(reader, head.Size+1))
	closeErr = reader.Close()
	if readErr != nil || closeErr != nil || !bytes.Equal(content, bytes.Join(parts, nil)) {
		return errors.New("multipart changed bytes")
	}
	return nil
}
