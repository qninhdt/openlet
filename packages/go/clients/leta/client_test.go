package leta

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letav1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/leta/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

type fakeAPI struct {
	binding func(context.Context, *letav1.GetLetaBindingRequest) (*letav1.GetLetaBindingResponse, error)
	list    func(context.Context, *letav1.ListWorkspaceLetaRequest) (*letav1.ListWorkspaceLetaResponse, error)
	stop    func(context.Context, *letav1.StopLetaForWorkspaceDeletionRequest) (*letav1.StopLetaForWorkspaceDeletionResponse, error)
}

func (f fakeAPI) ListWorkspaceLeta(ctx context.Context, in *letav1.ListWorkspaceLetaRequest, _ ...grpc.CallOption) (*letav1.ListWorkspaceLetaResponse, error) {
	return f.list(ctx, in)
}
func (f fakeAPI) StopLetaForWorkspaceDeletion(ctx context.Context, in *letav1.StopLetaForWorkspaceDeletionRequest, _ ...grpc.CallOption) (*letav1.StopLetaForWorkspaceDeletionResponse, error) {
	return f.stop(ctx, in)
}

func (f fakeAPI) GetLetaBinding(ctx context.Context, request *letav1.GetLetaBindingRequest, _ ...grpc.CallOption) (*letav1.GetLetaBindingResponse, error) {
	return f.binding(ctx, request)
}

func TestBindingValidatesCanonicalIdentityAndLifecycle(t *testing.T) {
	id, workspace, creator, home := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	for _, test := range []struct {
		name   string
		change func(*letav1.GetLetaBindingResponse)
		valid  bool
	}{
		{"initializing", func(r *letav1.GetLetaBindingResponse) { r.Status = "initializing" }, true},
		{"active", func(r *letav1.GetLetaBindingResponse) {}, true},
		{"deleting", func(r *letav1.GetLetaBindingResponse) { r.Status = "deleting" }, true},
		{"archived", func(r *letav1.GetLetaBindingResponse) { r.Status = "archived" }, true},
		{"foreign root", func(r *letav1.GetLetaBindingResponse) { r.LetaId = uuid.NewString() }, false},
		{"child", func(r *letav1.GetLetaBindingResponse) { r.Kind = "leti" }, false},
		{"workspace", func(r *letav1.GetLetaBindingResponse) { r.WorkspaceId = "invalid" }, false},
		{"creator", func(r *letav1.GetLetaBindingResponse) { r.CreatedByUserId = uuid.Nil.String() }, false},
		{"home", func(r *letav1.GetLetaBindingResponse) { r.HomeScopeId = "" }, false},
		{"lifecycle", func(r *letav1.GetLetaBindingResponse) { r.Status = "" }, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			response := &letav1.GetLetaBindingResponse{LetaId: id.String(), Kind: "leta", WorkspaceId: workspace.String(), CreatedByUserId: creator.String(), HomeScopeId: home.String(), Status: "active"}
			test.change(response)
			client := Client{API: fakeAPI{binding: func(ctx context.Context, request *letav1.GetLetaBindingRequest) (*letav1.GetLetaBindingResponse, error) {
				require.Equal(t, id.String(), request.LetaId)
				deadline, ok := ctx.Deadline()
				require.True(t, ok)
				require.LessOrEqual(t, time.Until(deadline), 10*time.Second)
				return response, nil
			}}}
			binding, err := client.GetBinding(t.Context(), id)
			if !test.valid {
				require.Equal(t, apperr.Unavailable, apperr.KindOf(err))
				return
			}
			require.NoError(t, err)
			require.Equal(t, Binding{id, workspace, creator, home, response.Status}, binding)
		})
	}
}

func TestBindingRejectsInvalidInputMissingResponseAndPreservesErrors(t *testing.T) {
	_, err := (Client{}).GetBinding(t.Context(), uuid.Nil)
	require.Equal(t, apperr.Invalid, apperr.KindOf(err))
	for _, failure := range []error{nil, status.Error(codes.NotFound, "resource not found"), status.Error(codes.Canceled, "request canceled")} {
		client := Client{API: fakeAPI{binding: func(context.Context, *letav1.GetLetaBindingRequest) (*letav1.GetLetaBindingResponse, error) {
			return nil, failure
		}}}
		_, err = client.GetBinding(t.Context(), uuid.New())
		if failure == nil {
			require.Equal(t, apperr.Unavailable, apperr.KindOf(err))
		} else if status.Code(failure) == codes.NotFound {
			require.Equal(t, apperr.Missing, apperr.KindOf(err))
		} else {
			require.Equal(t, apperr.Canceled, apperr.KindOf(err))
		}
	}
}
