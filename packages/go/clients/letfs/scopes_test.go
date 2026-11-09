package letfs

import (
	"context"
	"testing"

	"github.com/google/uuid"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
)

func (f fakeAdministration) ListScopes(ctx context.Context, input *letfsv1.ListScopesRequest, _ ...grpc.CallOption) (*letfsv1.ListScopesResponse, error) {
	return f.listScopes(ctx, input)
}

func TestListScopesValidatesBoundedCandidateMetadata(t *testing.T) {
	fs, a, b := uuid.New(), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	valid := func(id uuid.UUID) *letfsv1.Scope {
		return &letfsv1.Scope{Id: id.String(), FilesystemId: fs.String(), RootId: uuid.NewString(), State: "active", AllowBlobFiles: true}
	}
	response := &letfsv1.ListScopesResponse{Scopes: []*letfsv1.Scope{valid(a), valid(b)}, NextCursor: pointer("next-page")}
	client := Client{API: fakeAdministration{listScopes: func(_ context.Context, input *letfsv1.ListScopesRequest) (*letfsv1.ListScopesResponse, error) {
		require.Equal(t, fs.String(), input.GetFilesystemId())
		require.EqualValues(t, 2, input.GetLimit())
		require.Equal(t, "current-page", input.GetCursor())
		return response, nil
	}}}
	page, err := client.ListScopes(t.Context(), fs, 2, pointer("current-page"))
	require.NoError(t, err)
	require.Len(t, page.Items, 2)
	require.Equal(t, a, page.Items[0].ID)
	require.True(t, page.Items[0].AllowBlobFiles)
	require.False(t, page.Items[0].AllowIndexing)
	require.Equal(t, "next-page", *page.NextCursor)
	for name, malformed := range map[string]*letfsv1.ListScopesResponse{
		"nil response":            nil,
		"nil item":                {Scopes: []*letfsv1.Scope{nil}},
		"foreign filesystem":      {Scopes: []*letfsv1.Scope{{Id: a.String(), FilesystemId: uuid.NewString(), RootId: uuid.NewString(), State: "active"}}},
		"bad root":                {Scopes: []*letfsv1.Scope{{Id: a.String(), FilesystemId: fs.String(), RootId: "invalid", State: "active"}}},
		"inactive scope":          {Scopes: []*letfsv1.Scope{{Id: a.String(), FilesystemId: fs.String(), RootId: uuid.NewString(), State: "deleting"}}},
		"duplicate scope":         {Scopes: []*letfsv1.Scope{valid(a), valid(a)}},
		"out of order":            {Scopes: []*letfsv1.Scope{valid(b), valid(a)}},
		"oversized page":          {Scopes: []*letfsv1.Scope{valid(a), valid(b), valid(uuid.New())}},
		"empty with continuation": {NextCursor: pointer("next")},
		"repeated continuation":   {Scopes: []*letfsv1.Scope{valid(a)}, NextCursor: pointer("current-page")},
	} {
		t.Run(name, func(t *testing.T) {
			response = malformed
			_, err := client.ListScopes(t.Context(), fs, 2, pointer("current-page"))
			require.Error(t, err)
		})
	}
	response = &letfsv1.ListScopesResponse{}
	page, err = client.ListScopes(t.Context(), fs, 2, pointer("current-page"))
	require.NoError(t, err)
	require.Empty(t, page.Items)
	require.Nil(t, page.NextCursor)
}

func TestListScopesRejectsInvalidInputBeforeRPC(t *testing.T) {
	client := Client{}
	for _, test := range []struct {
		fs     uuid.UUID
		limit  int32
		cursor *string
	}{
		{uuid.Nil, 10, nil}, {uuid.New(), 0, nil}, {uuid.New(), 101, nil},
		{uuid.New(), 10, pointer("")},
	} {
		_, err := client.ListScopes(t.Context(), test.fs, test.limit, test.cursor)
		require.Error(t, err)
	}
}
