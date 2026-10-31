package user

import (
	"context"
	"encoding/json"
	"errors"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
)

type Client struct{ BaseURL, Token string }
type Summary struct {
	ID          uuid.UUID `json:"id"`
	DisplayName string    `json:"display_name"`
	AvatarURL   string    `json:"avatar_url"`
}

func (c Client) request(ctx context.Context, path string, out any) error {
	r, e := http.NewRequestWithContext(ctx, http.MethodGet, c.BaseURL+path, nil)
	if e != nil {
		return e
	}
	r.Header.Set("Authorization", "Bearer "+c.Token)
	r.Header.Set("Content-Type", "application/json")
	res, e := (&http.Client{Transport: otelhttp.NewTransport(http.DefaultTransport), Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}).Do(r)
	if e != nil {
		return errors.New("User unavailable")
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return errors.New("User request rejected")
	}
	return json.NewDecoder(io.LimitReader(res.Body, 1<<20)).Decode(out)
}
func (c Client) Summaries(ctx context.Context, ids []uuid.UUID) (map[uuid.UUID]Summary, error) {
	var v struct {
		Items []Summary `json:"items"`
	}
	if len(ids) == 0 {
		return map[uuid.UUID]Summary{}, nil
	}
	if len(ids) > 100 {
		return nil, errors.New("member summary limit exceeded")
	}
	values := make([]string, len(ids))
	for i, id := range ids {
		values[i] = id.String()
	}
	if e := c.request(ctx, "/internal/v1/users?ids="+strings.Join(values, ","), &v); e != nil {
		return nil, e
	}
	requested := map[uuid.UUID]bool{}
	for _, id := range ids {
		requested[id] = true
	}
	out := map[uuid.UUID]Summary{}
	for _, item := range v.Items {
		if !requested[item.ID] {
			return nil, errors.New("User summary scope mismatch")
		}
		if _, duplicate := out[item.ID]; duplicate {
			return nil, errors.New("duplicate User summary")
		}
		out[item.ID] = item
	}
	if len(out) != len(ids) {
		return nil, errors.New("missing User summary")
	}
	return out, nil
}
func (c Client) VerifiedEmails(ctx context.Context, id uuid.UUID) ([]string, error) {
	var v struct {
		Emails []string `json:"emails"`
	}
	e := c.request(ctx, "/internal/v1/users/"+id.String()+"/verified-emails", &v)
	return v.Emails, e
}
