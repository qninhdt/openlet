package user

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	accountv1 "openlet/packages/go/gen/openlet_api/account/v1"
)

type Client struct {
	API accountv1.AccountServiceClient
}
type Summary struct {
	ID          uuid.UUID `json:"id"`
	DisplayName string    `json:"display_name"`
	AvatarURL   string    `json:"avatar_url"`
}

func (c Client) Summaries(ctx context.Context, ids []uuid.UUID) (map[uuid.UUID]Summary, error) {
	if len(ids) == 0 {
		return map[uuid.UUID]Summary{}, nil
	}
	if len(ids) > 100 {
		return nil, errors.New("member summary limit exceeded")
	}
	values := make([]string, len(ids))
	requested := make(map[uuid.UUID]bool, len(ids))
	for i, id := range ids {
		if id == uuid.Nil || requested[id] {
			return nil, errors.New("invalid member summary identities")
		}
		requested[id], values[i] = true, id.String()
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	v, err := c.API.GetUserSummaries(ctx, &accountv1.GetUserSummariesRequest{Ids: values})
	if err != nil {
		return nil, err
	}
	out := map[uuid.UUID]Summary{}
	for _, item := range v.GetUsers() {
		id, err := uuid.Parse(item.GetId())
		if err != nil || !requested[id] {
			return nil, errors.New("User summary scope mismatch")
		}
		if _, duplicate := out[id]; duplicate {
			return nil, errors.New("duplicate User summary")
		}
		out[id] = Summary{ID: id, DisplayName: item.GetDisplayName(), AvatarURL: item.GetAvatarUrl()}
	}
	if len(out) != len(ids) {
		return nil, errors.New("missing User summary")
	}
	return out, nil
}
func (c Client) VerifiedEmails(ctx context.Context, id uuid.UUID) ([]string, error) {
	if id == uuid.Nil {
		return nil, errors.New("invalid user identity")
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	result, err := c.API.GetVerifiedEmails(ctx, &accountv1.GetVerifiedEmailsRequest{UserId: id.String()})
	if err != nil {
		return nil, err
	}
	return result.GetEmails(), nil
}
