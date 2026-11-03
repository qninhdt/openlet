package account

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	accountv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/account/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

type Summary struct {
	ID          uuid.UUID `json:"id"`
	DisplayName string    `json:"display_name"`
	AvatarURL   string    `json:"avatar_url"`
}

type Client struct {
	API accountv1.AccountServiceClient
}

func (c Client) Summaries(ctx context.Context, ids []uuid.UUID) (map[uuid.UUID]Summary, error) {
	if len(ids) == 0 {
		return map[uuid.UUID]Summary{}, nil
	}
	if len(ids) > 100 {
		return nil, apperr.New(apperr.Limit, "REQUEST_LIMIT", "member summary limit exceeded")
	}

	values := make([]string, len(ids))
	requested := make(map[uuid.UUID]bool, len(ids))
	for i, id := range ids {
		if id == uuid.Nil || requested[id] {
			return nil, apperr.New(apperr.Invalid, "VALIDATION", "invalid member summary identities")
		}
		requested[id], values[i] = true, id.String()
	}

	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	response, err := c.API.GetUserSummaries(ctx, &accountv1.GetUserSummariesRequest{Ids: values})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}

	result := make(map[uuid.UUID]Summary, len(ids))
	for _, item := range response.GetUsers() {
		id, err := uuid.Parse(item.GetId())
		if err != nil || !requested[id] {
			return nil, errors.New("user summary scope mismatch")
		}
		if _, duplicate := result[id]; duplicate {
			return nil, errors.New("duplicate user summary")
		}
		result[id] = Summary{ID: id, DisplayName: item.GetDisplayName(), AvatarURL: item.GetAvatarUrl()}
	}
	if len(result) != len(ids) {
		return nil, errors.New("missing user summary")
	}
	return result, nil
}

func (c Client) VerifiedEmails(ctx context.Context, id uuid.UUID) ([]string, error) {
	if id == uuid.Nil {
		return nil, apperr.New(apperr.Invalid, "VALIDATION", "invalid user identity")
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	response, err := c.API.GetVerifiedEmails(ctx, &accountv1.GetVerifiedEmailsRequest{UserId: id.String()})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	return response.GetEmails(), nil
}
