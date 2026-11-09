package leta

import (
	"context"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letav1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/leta/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"time"
)

// WorkspacePage enumerates canonical roots, including initializing and archived resources.
type WorkspacePage struct {
	IDs        []uuid.UUID
	NextCursor *uuid.UUID
}

func (c Client) ListWorkspaceLeta(ctx context.Context, workspaceID uuid.UUID, after *uuid.UUID) (WorkspacePage, error) {
	if workspaceID == uuid.Nil || (after != nil && *after == uuid.Nil) {
		return WorkspacePage{}, apperr.New(apperr.Invalid, "VALIDATION", "valid workspace/cursor required")
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	request := &letav1.ListWorkspaceLetaRequest{WorkspaceId: workspaceID.String(), Limit: 100}
	if after != nil {
		request.Cursor = after.String()
	}
	response, err := c.API.ListWorkspaceLeta(ctx, request)
	if err != nil {
		return WorkspacePage{}, rpc.DecodeError(err)
	}
	invalid := apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "invalid Leta inventory response")
	if response == nil || response.WorkspaceId != workspaceID.String() || len(response.LetaIds) > 100 {
		return WorkspacePage{}, invalid
	}
	result := WorkspacePage{IDs: make([]uuid.UUID, 0, len(response.LetaIds))}
	previous := uuid.Nil
	if after != nil {
		previous = *after
	}
	for _, raw := range response.LetaIds {
		id, err := uuid.Parse(raw)
		if err != nil || id == uuid.Nil || id.String() <= previous.String() {
			return WorkspacePage{}, invalid
		}
		result.IDs = append(result.IDs, id)
		previous = id
	}
	if response.NextCursor != nil {
		id, err := uuid.Parse(*response.NextCursor)
		if err != nil || len(result.IDs) == 0 || id != previous {
			return WorkspacePage{}, invalid
		}
		result.NextCursor = &id
	}
	return result, nil
}

func (c Client) StopLetaForWorkspaceDeletion(ctx context.Context, workspaceID, letaID uuid.UUID) error {
	if workspaceID == uuid.Nil || letaID == uuid.Nil {
		return apperr.New(apperr.Invalid, "VALIDATION", "workspace and Leta required")
	}
	ctx, cancel := context.WithTimeout(ctx, 90*time.Second)
	defer cancel()
	response, err := c.API.StopLetaForWorkspaceDeletion(ctx, &letav1.StopLetaForWorkspaceDeletionRequest{WorkspaceId: workspaceID.String(), LetaId: letaID.String()})
	if err != nil {
		return rpc.DecodeError(err)
	}
	if response == nil || response.WorkspaceId != workspaceID.String() || response.LetaId != letaID.String() || response.Status != "archived" {
		return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "Leta stop not acknowledged")
	}
	return nil
}
