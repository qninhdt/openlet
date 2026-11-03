package workspace

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	workspacev1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/workspace/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

type Client struct {
	API workspacev1.WorkspaceAdministrationServiceClient
}

func (c Client) EnsureInitial(ctx context.Context, actor uuid.UUID) (uuid.UUID, bool, error) {
	if actor == uuid.Nil {
		return uuid.Nil, false, apperr.New(apperr.Invalid, "VALIDATION", "invalid actor identity")
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	response, err := c.API.EnsureInitialWorkspace(ctx, &workspacev1.EnsureInitialWorkspaceRequest{
		ActorId: actor.String(), RequestKey: actor.String(), Name: "My workspace",
	})
	if err != nil {
		return uuid.Nil, false, rpc.DecodeError(err)
	}
	id, err := uuid.Parse(response.GetWorkspaceId())
	if err != nil || id == uuid.Nil {
		return uuid.Nil, false, apperr.New(apperr.Conflict, "WORKSPACE_SCOPE_CONFLICT", "invalid workspace result")
	}
	return id, response.GetCompleted(), nil
}
