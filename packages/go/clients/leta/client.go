package leta

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letav1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/leta/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

type Binding struct {
	LetaID          uuid.UUID
	WorkspaceID     uuid.UUID
	CreatedByUserID uuid.UUID
	HomeScopeID     uuid.UUID
	Status          string
}

type Client struct {
	API letav1.LetaServiceClient
}

func (c Client) GetBinding(ctx context.Context, id uuid.UUID) (Binding, error) {
	if id == uuid.Nil {
		return Binding{}, apperr.New(apperr.Invalid, "VALIDATION", "Leta identity required")
	}
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	response, err := c.API.GetLetaBinding(ctx, &letav1.GetLetaBindingRequest{LetaId: id.String()})
	if err != nil {
		return Binding{}, rpc.DecodeError(err)
	}
	invalid := apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "invalid Leta binding response")
	if response == nil || response.LetaId != id.String() || response.Kind != "leta" {
		return Binding{}, invalid
	}
	workspace, err := uuid.Parse(response.WorkspaceId)
	if err != nil || workspace == uuid.Nil {
		return Binding{}, invalid
	}
	creator, err := uuid.Parse(response.CreatedByUserId)
	if err != nil || creator == uuid.Nil {
		return Binding{}, invalid
	}
	home, err := uuid.Parse(response.HomeScopeId)
	if err != nil || home == uuid.Nil {
		return Binding{}, invalid
	}
	switch response.Status {
	case "initializing", "active", "deleting", "archived":
	default:
		return Binding{}, invalid
	}
	return Binding{LetaID: id, WorkspaceID: workspace, CreatedByUserID: creator, HomeScopeID: home, Status: response.Status}, nil
}
