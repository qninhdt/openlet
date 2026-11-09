package workspace

import (
	"bytes"
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	pb "github.com/qninhdt/openlet/packages/go/gen/openlet_api/workspace/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

type Client struct{ API pb.WorkspaceServiceClient }

func invalid() error {
	return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "invalid Workspace response")
}
func validID(value string) bool {
	id, err := uuid.Parse(value)
	return err == nil && id != uuid.Nil && id.String() == value
}
func actorContext(ctx context.Context, actor identity.Actor, timeout time.Duration) (context.Context, context.CancelFunc, error) {
	ctx, err := rpc.WithActor(ctx, actor)
	if err != nil {
		return nil, nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	return ctx, cancel, nil
}
func validWorkspace(value *pb.Workspace, ws uuid.UUID) bool {
	if value == nil || value.Id != ws.String() || !validID(value.FilesystemId) || !validID(value.SharedScopeId) {
		return false
	}
	switch value.Status {
	case "initializing", "active", "deleting", "deleted":
	default:
		return false
	}
	return true
}
func (c Client) GetWorkspace(ctx context.Context, ws uuid.UUID, actor identity.Actor) (*pb.Workspace, error) {
	if ws == uuid.Nil {
		return nil, invalid()
	}
	ctx, cancel, err := actorContext(ctx, actor, 15*time.Second)
	if err != nil {
		return nil, err
	}
	defer cancel()
	result, err := c.API.GetWorkspace(ctx, &pb.GetWorkspaceRequest{WorkspaceId: ws.String()})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	value := result.GetWorkspace()
	if !validWorkspace(value, ws) || value.Status != "active" {
		return nil, invalid()
	}
	if actor.Kind == identity.Leta && (value.Role != nil || value.PersonalScopeId != nil) {
		return nil, invalid()
	}
	if actor.Kind == identity.User && (!validID(value.GetPersonalScopeId()) || (value.GetRole() != "owner" && value.GetRole() != "admin" && value.GetRole() != "member")) {
		return nil, invalid()
	}
	return value, nil
}
func (c Client) GetCleanupWorkspace(ctx context.Context, ws, root uuid.UUID) (*pb.Workspace, error) {
	if ws == uuid.Nil || root == uuid.Nil {
		return nil, invalid()
	}
	ctx, cancel := context.WithTimeout(ctx, 15*time.Second)
	defer cancel()
	rootID := root.String()
	result, err := c.API.GetWorkspace(ctx, &pb.GetWorkspaceRequest{WorkspaceId: ws.String(), CleanupLetaId: &rootID})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	value := result.GetWorkspace()
	if !validWorkspace(value, ws) || (value.Status != "deleting" && value.Status != "deleted") || value.Name != "" || value.Role != nil || value.PersonalScopeId != nil {
		return nil, invalid()
	}
	return value, nil
}
func (c Client) ListMembers(ctx context.Context, ws uuid.UUID, actor identity.Actor, limit int32, cursor *string) (*pb.ListMembersResponse, error) {
	if ws == uuid.Nil || limit < 1 || limit > 100 || (cursor != nil && !validID(*cursor)) {
		return nil, invalid()
	}
	ctx, cancel, err := actorContext(ctx, actor, 15*time.Second)
	if err != nil {
		return nil, err
	}
	defer cancel()
	result, err := c.API.ListMembers(ctx, &pb.ListMembersRequest{WorkspaceId: ws.String(), Limit: limit, Cursor: cursor})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	if result == nil || result.WorkspaceId != ws.String() || len(result.Items) > int(limit) {
		return nil, invalid()
	}
	previous := uuid.Nil
	if cursor != nil {
		previous, _ = uuid.Parse(*cursor)
	}
	for _, item := range result.Items {
		if item == nil || item.User == nil || !validID(item.User.Id) || !validID(item.PersonalScopeId) || (item.Role != "owner" && item.Role != "admin" && item.Role != "member") {
			return nil, invalid()
		}
		current, _ := uuid.Parse(item.User.Id)
		if bytes.Compare(current[:], previous[:]) <= 0 {
			return nil, invalid()
		}
		previous = current
	}
	if result.NextCursor != nil && (len(result.Items) == 0 || *result.NextCursor != previous.String()) {
		return nil, invalid()
	}
	return result, nil
}
func (c Client) ListAccessibleScopes(ctx context.Context, ws uuid.UUID, actor identity.Actor, inspect *uuid.UUID, limit int32, cursor *string) (*pb.ListAccessibleScopesResponse, error) {
	if ws == uuid.Nil || limit < 1 || limit > 100 || (cursor != nil && (len(*cursor) == 0 || len(*cursor) > 2048)) {
		return nil, invalid()
	}
	subject := actor
	var letaID *string
	if inspect != nil {
		if actor.Kind != identity.User || *inspect == uuid.Nil {
			return nil, invalid()
		}
		v := inspect.String()
		letaID = &v
		subject = identity.Actor{Kind: identity.Leta, ID: *inspect}
	}
	ctx, cancel, err := actorContext(ctx, actor, 20*time.Second)
	if err != nil {
		return nil, err
	}
	defer cancel()
	result, err := c.API.ListAccessibleScopes(ctx, &pb.ListAccessibleScopesRequest{WorkspaceId: ws.String(), LetaId: letaID, Limit: limit, Cursor: cursor})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	if result == nil || result.WorkspaceId != ws.String() || !validID(result.FilesystemId) || result.SubjectKind != string(subject.Kind) || result.SubjectId != subject.ID.String() || len(result.Items) > int(limit) {
		return nil, invalid()
	}
	previous := uuid.Nil
	roots := map[string]bool{}
	for _, item := range result.Items {
		if item == nil || !validID(item.Id) || !validID(item.RootId) || roots[item.RootId] || item.Rights == nil || !item.Rights.ReadMetadata {
			return nil, invalid()
		}
		current, _ := uuid.Parse(item.Id)
		if bytes.Compare(current[:], previous[:]) <= 0 {
			return nil, invalid()
		}
		previous = current
		roots[item.RootId] = true
		switch item.Kind {
		case "scope", "shared", "home":
			if item.Owner != nil {
				return nil, invalid()
			}
		case "personal":
			if item.Owner == nil || !validID(item.Owner.Id) {
				return nil, invalid()
			}
		default:
			return nil, invalid()
		}
	}
	if result.NextCursor != nil && (len(*result.NextCursor) == 0 || len(*result.NextCursor) > 2048 || (cursor != nil && *cursor == *result.NextCursor)) {
		return nil, invalid()
	}
	return result, nil
}
func (c Client) EnsureLetaHomeAccess(ctx context.Context, ws, root, home, key uuid.UUID, creator identity.Actor) (*pb.EnsureLetaHomeAccessResponse, error) {
	if ws == uuid.Nil || root == uuid.Nil || home == uuid.Nil || key == uuid.Nil || creator.Kind != identity.User {
		return nil, invalid()
	}
	ctx, cancel, err := actorContext(ctx, creator, 60*time.Second)
	if err != nil {
		return nil, err
	}
	defer cancel()
	result, err := c.API.EnsureLetaHomeAccess(ctx, &pb.EnsureLetaHomeAccessRequest{WorkspaceId: ws.String(), LetaId: root.String(), HomeScopeId: home.String(), IdempotencyKey: key.String()})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	if result == nil || result.WorkspaceId != ws.String() || result.HomeScopeId != home.String() || !validID(result.FilesystemId) {
		return nil, invalid()
	}
	return result, nil
}
func (c Client) ResolvePersonalScope(ctx context.Context, ws, owner uuid.UUID, root identity.Actor) (*pb.ResolvePersonalScopeResponse, error) {
	if ws == uuid.Nil || owner == uuid.Nil || root.Kind != identity.Leta {
		return nil, invalid()
	}
	ctx, cancel, err := actorContext(ctx, root, 15*time.Second)
	if err != nil {
		return nil, err
	}
	defer cancel()
	result, err := c.API.ResolvePersonalScope(ctx, &pb.ResolvePersonalScopeRequest{WorkspaceId: ws.String(), OwnerUserId: owner.String()})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	if result == nil || result.WorkspaceId != ws.String() || result.OwnerUserId != owner.String() || !validID(result.FilesystemId) || !validID(result.ScopeId) {
		return nil, invalid()
	}
	return result, nil
}
func (c Client) ChangeScopeAccess(ctx context.Context, actor identity.Actor, in *pb.ChangeScopeAccessRequest) (*pb.ChangeScopeAccessResponse, error) {
	if in == nil || actor.Kind != identity.User || !validID(in.WorkspaceId) || !validID(in.ScopeId) || !validID(in.GranteeId) || !validID(in.IdempotencyKey) || (in.GranteeKind != "user" && in.GranteeKind != "leta") || (in.Role != "viewer" && in.Role != "editor" && in.Role != "manager") || (in.GranteeKind == "leta" && in.Role == "manager") || (in.PersonalOwnerUserId != nil && (!validID(*in.PersonalOwnerUserId) || *in.PersonalOwnerUserId != actor.ID.String() || in.GranteeKind != "leta" || in.Revoke)) {
		return nil, invalid()
	}
	ctx, cancel, err := actorContext(ctx, actor, 60*time.Second)
	if err != nil {
		return nil, err
	}
	defer cancel()
	result, err := c.API.ChangeScopeAccess(ctx, in)
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	if result == nil || result.WorkspaceId != in.WorkspaceId || result.ScopeId != in.ScopeId || result.GranteeKind != in.GranteeKind || result.GranteeId != in.GranteeId || result.Rights == nil {
		return nil, invalid()
	}
	return result, nil
}
func (c Client) CleanupLetaAccess(ctx context.Context, ws, root, home uuid.UUID, creator *identity.Actor) error {
	if ws == uuid.Nil || root == uuid.Nil || home == uuid.Nil {
		return invalid()
	}
	if creator != nil {
		if creator.Kind != identity.User {
			return invalid()
		}
		var err error
		ctx, err = rpc.WithActor(ctx, *creator)
		if err != nil {
			return err
		}
	}
	ctx, cancel := context.WithTimeout(ctx, 90*time.Second)
	defer cancel()
	result, err := c.API.CleanupLetaAccess(ctx, &pb.CleanupLetaAccessRequest{WorkspaceId: ws.String(), LetaId: root.String(), HomeScopeId: home.String()})
	if err != nil {
		return rpc.DecodeError(err)
	}
	if !result.GetCompleted() {
		return invalid()
	}
	return nil
}
