package user

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"time"

	"github.com/google/uuid"
)

type Client struct{ BaseURL, Token string }
type Summary struct {
	ID          uuid.UUID `json:"id"`
	DisplayName string    `json:"display_name"`
	AvatarURL   string    `json:"avatar_url"`
}

func (c Client) request(ctx context.Context, method, path string, in, out any) error {
	var body io.Reader
	if in != nil {
		b, e := json.Marshal(in)
		if e != nil {
			return e
		}
		body = bytes.NewReader(b)
	}
	r, e := http.NewRequestWithContext(ctx, method, c.BaseURL+path, body)
	if e != nil {
		return e
	}
	r.Header.Set("Authorization", "Bearer "+c.Token)
	r.Header.Set("Content-Type", "application/json")
	res, e := (&http.Client{Timeout: 10 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}).Do(r)
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
	if e := c.request(ctx, "POST", "/internal/v1/user-summaries", map[string]any{"ids": ids}, &v); e != nil {
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
	e := c.request(ctx, "GET", "/internal/v1/users/"+id.String()+"/verified-emails", nil, &v)
	return v.Emails, e
}
