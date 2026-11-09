package leta

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letav1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/leta/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestWorkspaceInventoryValidatesScopeOrderAndProgress(t *testing.T) {
	ws, first, second := uuid.New(), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	for _, test := range []struct {
		name   string
		change func(*letav1.ListWorkspaceLetaResponse)
		valid  bool
	}{
		{"valid", func(*letav1.ListWorkspaceLetaResponse) {}, true},
		{"foreign workspace", func(r *letav1.ListWorkspaceLetaResponse) { r.WorkspaceId = uuid.NewString() }, false},
		{"duplicate root", func(r *letav1.ListWorkspaceLetaResponse) { r.LetaIds = []string{second.String(), second.String()} }, false},
		{"backward root", func(r *letav1.ListWorkspaceLetaResponse) { r.LetaIds = []string{first.String()} }, false},
		{"null root", func(r *letav1.ListWorkspaceLetaResponse) { r.LetaIds = []string{uuid.Nil.String()} }, false},
		{"nonadvancing cursor", func(r *letav1.ListWorkspaceLetaResponse) { r.NextCursor = new(first.String()) }, false},
		{"empty cursor page", func(r *letav1.ListWorkspaceLetaResponse) { r.LetaIds = nil }, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			response := &letav1.ListWorkspaceLetaResponse{WorkspaceId: ws.String(), LetaIds: []string{second.String()}, NextCursor: new(second.String())}
			test.change(response)
			client := Client{API: fakeAPI{list: func(ctx context.Context, in *letav1.ListWorkspaceLetaRequest) (*letav1.ListWorkspaceLetaResponse, error) {
				require.Equal(t, ws.String(), in.WorkspaceId)
				require.Equal(t, first.String(), in.Cursor)
				require.EqualValues(t, 100, in.Limit)
				deadline, ok := ctx.Deadline()
				require.True(t, ok)
				require.LessOrEqual(t, time.Until(deadline), 10*time.Second)
				return response, nil
			}}}
			page, err := client.ListWorkspaceLeta(t.Context(), ws, &first)
			if !test.valid {
				require.Equal(t, apperr.Unavailable, apperr.KindOf(err))
				return
			}
			require.NoError(t, err)
			require.Equal(t, []uuid.UUID{second}, page.IDs)
			require.Equal(t, second, *page.NextCursor)
		})
	}
}

func TestWorkspaceStopRequiresAcknowledgedArchiveAndPreservesRemoteError(t *testing.T) {
	ws, root := uuid.New(), uuid.New()
	for _, state := range []string{"active", "deleting", "archived"} {
		client := Client{API: fakeAPI{stop: func(ctx context.Context, in *letav1.StopLetaForWorkspaceDeletionRequest) (*letav1.StopLetaForWorkspaceDeletionResponse, error) {
			require.Equal(t, ws.String(), in.WorkspaceId)
			require.Equal(t, root.String(), in.LetaId)
			return &letav1.StopLetaForWorkspaceDeletionResponse{WorkspaceId: ws.String(), LetaId: root.String(), Status: state}, nil
		}}}
		err := client.StopLetaForWorkspaceDeletion(t.Context(), ws, root)
		if state == "archived" {
			require.NoError(t, err)
		} else {
			require.Equal(t, apperr.Unavailable, apperr.KindOf(err))
		}
	}
	client := Client{API: fakeAPI{stop: func(context.Context, *letav1.StopLetaForWorkspaceDeletionRequest) (*letav1.StopLetaForWorkspaceDeletionResponse, error) {
		return nil, status.Error(codes.Unavailable, "unavailable")
	}}}
	require.Equal(t, apperr.Unavailable, apperr.KindOf(client.StopLetaForWorkspaceDeletion(t.Context(), ws, root)))
	require.Equal(t, apperr.Invalid, apperr.KindOf(client.StopLetaForWorkspaceDeletion(t.Context(), uuid.Nil, root)))
}
