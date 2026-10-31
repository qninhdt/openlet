package clerk

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"io"
	"net/http"
	"net/url"
	"time"
)

type Client struct{ BaseURL, Secret string }

func (c Client) request(ctx context.Context, method, path string, body any, out any) error {
	var reader io.Reader
	if body != nil {
		b, e := json.Marshal(body)
		if e != nil {
			return e
		}
		reader = bytes.NewReader(b)
	}
	r, e := http.NewRequestWithContext(ctx, method, c.BaseURL+path, reader)
	if e != nil {
		return errors.New("Clerk request failed")
	}
	r.Header.Set("Authorization", "Bearer "+c.Secret)
	r.Header.Set("Content-Type", "application/json")
	res, e := (&http.Client{Transport: otelhttp.NewTransport(http.DefaultTransport), Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}).Do(r)
	if e != nil {
		return errors.New("Clerk unavailable")
	}
	defer res.Body.Close()
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		return errors.New("Clerk request rejected")
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(out)
}
func (c Client) PublishUserID(ctx context.Context, subject, id string) error {
	return c.request(ctx, http.MethodPatch, "/users/"+url.PathEscape(subject)+"/metadata", map[string]any{"public_metadata": map[string]string{"openlet_user_id": id}}, nil)
}
func (c Client) VerifiedEmails(ctx context.Context, subject string) ([]string, error) {
	var v struct {
		Emails []struct {
			Email        string `json:"email_address"`
			Verification struct {
				Status string `json:"status"`
			} `json:"verification"`
		} `json:"email_addresses"`
	}
	if e := c.request(ctx, http.MethodGet, "/users/"+url.PathEscape(subject), nil, &v); e != nil {
		return nil, e
	}
	out := make([]string, 0, len(v.Emails))
	for _, email := range v.Emails {
		if email.Verification.Status == "verified" {
			out = append(out, email.Email)
		}
	}
	return out, nil
}
