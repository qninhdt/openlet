//go:build integration

package user

import (
	"context"
	"net"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	accountv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/account/v1"
	sharedrpc "github.com/qninhdt/openlet/packages/go/rpc"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type accountFixture struct {
	accountv1.UnimplementedAccountServiceServer
	summaries func(context.Context, *accountv1.GetUserSummariesRequest) (*accountv1.GetUserSummariesResponse, error)
	emails    func(context.Context, *accountv1.GetVerifiedEmailsRequest) (*accountv1.GetVerifiedEmailsResponse, error)
}

func (s accountFixture) GetUserSummaries(ctx context.Context, request *accountv1.GetUserSummariesRequest) (*accountv1.GetUserSummariesResponse, error) {
	return s.summaries(ctx, request)
}
func (s accountFixture) GetVerifiedEmails(ctx context.Context, request *accountv1.GetVerifiedEmailsRequest) (*accountv1.GetVerifiedEmailsResponse, error) {
	return s.emails(ctx, request)
}

func accountClient(t *testing.T, fixture accountFixture) Client {
	t.Helper()
	token := strings.Repeat("w", 32)
	authentication, err := sharedrpc.NewAuthenticator([]sharedrpc.Credential{{Service: "workspace", Token: token, Methods: []string{
		accountv1.AccountService_GetUserSummaries_FullMethodName,
		accountv1.AccountService_GetVerifiedEmails_FullMethodName,
	}}})
	require.NoError(t, err)
	server, err := sharedrpc.NewServer(authentication, sharedrpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	accountv1.RegisterAccountServiceServer(server, fixture)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	stopped := make(chan error, 1)
	go func() { stopped <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-stopped) })
	connection, err := sharedrpc.Dial(listener.Addr().String(), token, sharedrpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	return Client{API: accountv1.NewAccountServiceClient(connection)}
}

func TestIntegrationSummariesRequireExactResponseScope(t *testing.T) {
	first, second := uuid.New(), uuid.New()
	for _, test := range []struct {
		name  string
		users []*accountv1.UserSummary
		valid bool
	}{
		{"reordered exact set", []*accountv1.UserSummary{{Id: second.String()}, {Id: first.String(), DisplayName: "Việt", AvatarUrl: "https://example.test/avatar"}}, true},
		{"missing", []*accountv1.UserSummary{{Id: first.String()}}, false},
		{"duplicate", []*accountv1.UserSummary{{Id: first.String()}, {Id: first.String()}}, false},
		{"foreign", []*accountv1.UserSummary{{Id: first.String()}, {Id: uuid.NewString()}}, false},
		{"malformed", []*accountv1.UserSummary{{Id: first.String()}, {Id: "invalid"}}, false},
		{"nil identity", []*accountv1.UserSummary{{Id: first.String()}, {Id: uuid.Nil.String()}}, false},
		{"nil entry", []*accountv1.UserSummary{{Id: first.String()}, nil}, false},
		{"empty", nil, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			requests := make(chan *accountv1.GetUserSummariesRequest, 1)
			client := accountClient(t, accountFixture{summaries: func(_ context.Context, request *accountv1.GetUserSummariesRequest) (*accountv1.GetUserSummariesResponse, error) {
				requests <- request
				return &accountv1.GetUserSummariesResponse{Users: test.users}, nil
			}})
			result, err := client.Summaries(t.Context(), []uuid.UUID{first, second})
			require.Equal(t, []string{first.String(), second.String()}, (<-requests).Ids)
			if !test.valid {
				require.Error(t, err)
				require.Nil(t, result)
				return
			}
			require.NoError(t, err)
			require.Len(t, result, 2)
			require.Equal(t, Summary{ID: first, DisplayName: "Việt", AvatarURL: "https://example.test/avatar"}, result[first])
		})
	}
}

func TestIntegrationLookupInputAndDependencyFailures(t *testing.T) {
	var calls atomic.Int32
	client := accountClient(t, accountFixture{
		summaries: func(context.Context, *accountv1.GetUserSummariesRequest) (*accountv1.GetUserSummariesResponse, error) {
			calls.Add(1)
			return nil, sharedrpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "account unavailable")
		},
		emails: func(context.Context, *accountv1.GetVerifiedEmailsRequest) (*accountv1.GetVerifiedEmailsResponse, error) {
			calls.Add(1)
			return nil, sharedrpc.Fault(codes.NotFound, "NOT_FOUND", "active user not found")
		},
	})
	result, err := client.Summaries(t.Context(), nil)
	require.NoError(t, err)
	require.Empty(t, result)
	id := uuid.New()
	for _, ids := range [][]uuid.UUID{{uuid.Nil}, {id, id}, make([]uuid.UUID, 101)} {
		_, err := client.Summaries(t.Context(), ids)
		require.Error(t, err)
	}
	_, err = client.VerifiedEmails(t.Context(), uuid.Nil)
	require.Error(t, err)
	require.Zero(t, calls.Load(), "invalid inputs must not reach Account")
	_, err = client.Summaries(t.Context(), []uuid.UUID{id})
	require.Equal(t, codes.Unavailable, status.Code(err))
	_, err = client.VerifiedEmails(t.Context(), id)
	require.Equal(t, codes.NotFound, status.Code(err))
	require.Equal(t, int32(2), calls.Load())
}

func TestIntegrationEmailLookupPreservesIdentityAndDeadline(t *testing.T) {
	type observed struct {
		id       string
		deadline time.Time
	}
	requests := make(chan observed, 2)
	client := accountClient(t, accountFixture{emails: func(ctx context.Context, request *accountv1.GetVerifiedEmailsRequest) (*accountv1.GetVerifiedEmailsResponse, error) {
		deadline, _ := ctx.Deadline()
		requests <- observed{request.UserId, deadline}
		return &accountv1.GetVerifiedEmailsResponse{Emails: []string{"verified@example.test"}}, nil
	}})
	id := uuid.New()
	for _, timeout := range []time.Duration{time.Minute, 3 * time.Second} {
		ctx, cancel := context.WithTimeout(t.Context(), timeout)
		started := time.Now()
		emails, err := client.VerifiedEmails(ctx, id)
		cancel()
		require.NoError(t, err)
		require.Equal(t, []string{"verified@example.test"}, emails)
		request := <-requests
		require.Equal(t, id.String(), request.id)
		limit := min(timeout, 10*time.Second)
		require.WithinDuration(t, started.Add(limit), request.deadline, time.Second)
	}
}

func TestIntegrationLookupCancellationReachesAccount(t *testing.T) {
	entered, canceled := make(chan struct{}), make(chan struct{})
	client := accountClient(t, accountFixture{summaries: func(ctx context.Context, _ *accountv1.GetUserSummariesRequest) (*accountv1.GetUserSummariesResponse, error) {
		close(entered)
		<-ctx.Done()
		close(canceled)
		return nil, ctx.Err()
	}})
	ctx, cancel := context.WithTimeout(t.Context(), 5*time.Second)
	defer cancel()
	finished := make(chan error, 1)
	go func() { _, err := client.Summaries(ctx, []uuid.UUID{uuid.New()}); finished <- err }()
	select {
	case <-entered:
	case <-ctx.Done():
		t.Fatal("Account did not receive lookup")
	}
	cancel()
	select {
	case err := <-finished:
		require.Equal(t, codes.Canceled, status.Code(err))
	case <-time.After(5 * time.Second):
		t.Fatal("client did not cancel")
	}
	select {
	case <-canceled:
	case <-time.After(5 * time.Second):
		t.Fatal("Account did not observe cancellation")
	}
}
