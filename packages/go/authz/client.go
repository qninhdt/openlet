package authz

import (
	"context"
	"errors"
	"github.com/qninhdt/openlet/packages/go/apperr"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
)

var ErrInvalidCheck = errors.New("invalid authorization check")
var ErrInvalidResponse = errors.New("authorization response does not match the requested checks")

type Resource struct {
	Type string
	ID   string
}

// Check uses the official client and never falls back to a local role decision.
func Check(ctx context.Context, client v1.PermissionsServiceClient, actor string, action Action, resource Resource) (bool, error) {
	if actor == "" || resource.ID == "" || !action.Valid(resource.Type) {
		return false, ErrInvalidCheck
	}
	response, err := client.CheckPermission(ctx, &v1.CheckPermissionRequest{
		Consistency: fullyConsistent(),
		Resource:    &v1.ObjectReference{ObjectType: resource.Type, ObjectId: resource.ID},
		Permission:  string(action),
		Subject:     &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: "user", ObjectId: actor}},
	})
	if err != nil {
		return false, dependencyError(ctx, err)
	}
	return response.Permissionship == v1.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION, nil
}

func fullyConsistent() *v1.Consistency {
	return &v1.Consistency{Requirement: &v1.Consistency_FullyConsistent{FullyConsistent: true}}
}

// BulkCheck returns decisions in candidate order, using one fully consistent graph request.
func BulkCheck(ctx context.Context, client v1.PermissionsServiceClient, actor string, action Action, resources []Resource) ([]bool, error) {
	if actor == "" || len(resources) == 0 || len(resources) > 100 {
		return nil, ErrInvalidCheck
	}
	items := make([]*v1.CheckBulkPermissionsRequestItem, len(resources))
	indices := make(map[Resource]int, len(resources))
	for i, resource := range resources {
		if _, duplicate := indices[resource]; duplicate || resource.ID == "" || !action.Valid(resource.Type) {
			return nil, ErrInvalidCheck
		}
		indices[resource] = i
		items[i] = &v1.CheckBulkPermissionsRequestItem{
			Resource: &v1.ObjectReference{ObjectType: resource.Type, ObjectId: resource.ID}, Permission: string(action),
			Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: "user", ObjectId: actor}},
		}
	}
	response, err := client.CheckBulkPermissions(ctx, &v1.CheckBulkPermissionsRequest{Consistency: fullyConsistent(), Items: items})
	if err != nil {
		return nil, dependencyError(ctx, err)
	}
	if len(response.GetPairs()) != len(items) {
		return nil, ErrInvalidResponse
	}
	allowed := make([]bool, len(items))
	for _, pair := range response.Pairs {
		resource := pair.GetRequest().GetResource()
		key := Resource{Type: resource.GetObjectType(), ID: resource.GetObjectId()}
		i, found := indices[key]
		if !found || !proto.Equal(pair.GetRequest(), items[i]) {
			return nil, ErrInvalidResponse
		}
		delete(indices, key)
		if pair.GetError() != nil {
			err := status.ErrorProto(pair.GetError())
			if err == nil {
				return nil, ErrInvalidResponse
			}
			return nil, dependencyError(ctx, err)
		}
		if pair.GetItem() == nil {
			return nil, ErrInvalidResponse
		}
		allowed[i] = pair.GetItem().Permissionship == v1.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION
	}
	return allowed, nil
}

func dependencyError(ctx context.Context, err error) error {
	if ctx.Err() != nil {
		return ctx.Err()
	}
	return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "authorization unavailable")
}
