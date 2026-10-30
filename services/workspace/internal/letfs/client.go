package letfs

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/google/uuid"
)

type Client struct {
	BaseURL string
	Token   string
}
type BucketInput struct {
	ID           uuid.UUID `json:"id"`
	ProvisionKey string    `json:"provision_key"`
	LimitBytes   string    `json:"limit_bytes"`
}
type Bucket struct {
	ID         uuid.UUID `json:"id"`
	LimitBytes string    `json:"limit_bytes"`
	UsedBytes  string    `json:"used_bytes"`
	State      string    `json:"state"`
}
type FilesystemInput struct {
	ID           uuid.UUID `json:"id"`
	BucketID     uuid.UUID `json:"bucket_id"`
	RootID       uuid.UUID `json:"root_id"`
	ProvisionKey string    `json:"provision_key"`
	RootName     string    `json:"root_name"`
}
type Filesystem struct {
	ID       uuid.UUID `json:"id"`
	BucketID uuid.UUID `json:"bucket_id"`
	RootID   uuid.UUID `json:"root_id"`
	State    string    `json:"state"`
}
type Error struct{ Status int }

func (e Error) Error() string { return fmt.Sprintf("letfs returned status %d", e.Status) }
func (c *Client) post(ctx context.Context, path string, in, out any) error {
	return c.request(ctx, http.MethodPost, path, in, out)
}
func (c *Client) request(ctx context.Context, method, path string, in, out any) error {
	b, e := json.Marshal(in)
	if e != nil {
		return e
	}
	r, e := http.NewRequestWithContext(ctx, method, c.BaseURL+path, bytes.NewReader(b))
	if e != nil {
		return e
	}
	r.Header.Set("Authorization", "Bearer "+c.Token)
	r.Header.Set("Content-Type", "application/json")
	res, e := (&http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}).Do(r)
	if e != nil {
		return errors.New("letfs unavailable")
	}
	defer res.Body.Close()
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return Error{res.StatusCode}
	}
	return json.NewDecoder(io.LimitReader(res.Body, 65536)).Decode(out)
}
func (c *Client) EnsureBucket(ctx context.Context, in BucketInput) (Bucket, error) {
	var result Bucket
	e := c.post(ctx, "/internal/v1/quota-buckets/ensure", in, &result)
	if e == nil && (result.ID != in.ID || result.LimitBytes != in.LimitBytes || result.State != "active") {
		e = errors.New("letfs scope mismatch")
	}
	return result, e
}
func (c *Client) EnsureFilesystem(ctx context.Context, in FilesystemInput) (Filesystem, error) {
	var result Filesystem
	e := c.post(ctx, "/internal/v1/filesystems/ensure", in, &result)
	if e == nil && (result.ID != in.ID || result.BucketID != in.BucketID || result.RootID != in.RootID || result.State != "active") {
		e = errors.New("letfs scope mismatch")
	}
	return result, e
}
