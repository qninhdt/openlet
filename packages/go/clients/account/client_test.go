package account

import (
	"context"
	"testing"

	"github.com/google/uuid"
	accountv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/account/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
)

type fakeAPI struct {
	summaries func(context.Context, *accountv1.GetUserSummariesRequest) (*accountv1.GetUserSummariesResponse, error)
	emails    func(context.Context, *accountv1.GetVerifiedEmailsRequest) (*accountv1.GetVerifiedEmailsResponse, error)
}

func (f fakeAPI) GetUserSummaries(ctx context.Context, request *accountv1.GetUserSummariesRequest, _ ...grpc.CallOption) (*accountv1.GetUserSummariesResponse, error) {
	return f.summaries(ctx, request)
}

func (f fakeAPI) GetVerifiedEmails(ctx context.Context, request *accountv1.GetVerifiedEmailsRequest, _ ...grpc.CallOption) (*accountv1.GetVerifiedEmailsResponse, error) {
	return f.emails(ctx, request)
}

func TestSummariesRequireExactResponseScope(t *testing.T) {
	first, second := uuid.New(), uuid.New()
	for _, test := range []struct {
		name  string
		users []*accountv1.UserSummary
		valid bool
	}{
		{"exact set", []*accountv1.UserSummary{{Id: second.String()}, {Id: first.String(), DisplayName: "Việt"}}, true},
		{"missing", []*accountv1.UserSummary{{Id: first.String()}}, false},
		{"duplicate", []*accountv1.UserSummary{{Id: first.String()}, {Id: first.String()}}, false},
		{"foreign", []*accountv1.UserSummary{{Id: first.String()}, {Id: uuid.NewString()}}, false},
		{"malformed", []*accountv1.UserSummary{{Id: first.String()}, {Id: "invalid"}}, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			client := Client{API: fakeAPI{summaries: func(_ context.Context, request *accountv1.GetUserSummariesRequest) (*accountv1.GetUserSummariesResponse, error) {
				require.Equal(t, []string{first.String(), second.String()}, request.GetIds())
				return &accountv1.GetUserSummariesResponse{Users: test.users}, nil
			}}}
			result, err := client.Summaries(t.Context(), []uuid.UUID{first, second})
			if !test.valid {
				require.Error(t, err)
				return
			}
			require.NoError(t, err)
			require.Equal(t, "Việt", result[first].DisplayName)
		})
	}
}

func TestInvalidInputsDoNotReachAccount(t *testing.T) {
	calls := 0
	client := Client{API: fakeAPI{
		summaries: func(context.Context, *accountv1.GetUserSummariesRequest) (*accountv1.GetUserSummariesResponse, error) {
			calls++
			return nil, nil
		},
		emails: func(context.Context, *accountv1.GetVerifiedEmailsRequest) (*accountv1.GetVerifiedEmailsResponse, error) {
			calls++
			return nil, nil
		},
	}}
	id := uuid.New()
	for _, ids := range [][]uuid.UUID{{uuid.Nil}, {id, id}, make([]uuid.UUID, 101)} {
		_, err := client.Summaries(t.Context(), ids)
		require.Error(t, err)
	}
	_, err := client.VerifiedEmails(t.Context(), uuid.Nil)
	require.Error(t, err)
	require.Zero(t, calls)
}
