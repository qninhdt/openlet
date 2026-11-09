package authz

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/identity"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

var testActor = identity.Actor{Kind: identity.User, ID: uuid.MustParse("019a3b66-0000-7000-8000-000000000001")}

func TestCheckRejectsUnsupportedOrWrongScopeBeforeRPC(t *testing.T) {
	for _, test := range []struct {
		actor    identity.Actor
		action   Action
		resource Resource
	}{
		{identity.Actor{}, ScopeReadMetadata, Resource{"scope", "file-system"}},
		{testActor, ScopeReadMetadata, Resource{"scope", ""}},
		{testActor, Action("owner"), Resource{"scope", "file-system"}},
		{testActor, ScopeManageAccess, Resource{"filesystem", "file-system"}},
		{testActor, ScopeReadMetadata, Resource{"workspace", "team"}},
	} {
		allowed, err := Check(context.Background(), nil, test.actor, test.action, test.resource)
		if allowed || !errors.Is(err, ErrInvalidCheck) {
			t.Fatalf("%+v: got %v, %v", test, allowed, err)
		}
	}
}

func TestBulkCheckRejectsInvalidCandidatesBeforeRPC(t *testing.T) {
	for _, resources := range [][]Resource{
		nil, make([]Resource, 101), {{Type: "scope"}},
		{{Type: "workspace", ID: "team"}},
		{{Type: "scope", ID: "same"}, {Type: "scope", ID: "same"}},
	} {
		_, err := BulkCheck(t.Context(), nil, testActor, ScopeReadMetadata, resources)
		require.ErrorIs(t, err, ErrInvalidCheck)
	}
	_, err := BulkCheck(t.Context(), nil, identity.Actor{}, ScopeReadMetadata, []Resource{{Type: "scope", ID: "fs"}})
	require.ErrorIs(t, err, ErrInvalidCheck)
}

type bulkClient struct {
	v1.PermissionsServiceClient
	call func(*v1.CheckBulkPermissionsRequest) (*v1.CheckBulkPermissionsResponse, error)
}

func (c bulkClient) CheckBulkPermissions(_ context.Context, request *v1.CheckBulkPermissionsRequest, _ ...grpc.CallOption) (*v1.CheckBulkPermissionsResponse, error) {
	return c.call(request)
}

func TestBulkCheckMatchesEveryResultToItsRequestedScope(t *testing.T) {
	resources := []Resource{{Type: "scope", ID: "allowed"}, {Type: "scope", ID: "denied"}}
	for _, mode := range []string{"reordered", "missing", "duplicate", "foreign", "wrong_actor", "wrong_kind", "wrong_action", "no_result", "item_error", "invalid_error", "outage", "nil"} {
		t.Run(mode, func(t *testing.T) {
			client := bulkClient{call: func(request *v1.CheckBulkPermissionsRequest) (*v1.CheckBulkPermissionsResponse, error) {
				require.True(t, request.Consistency.GetFullyConsistent())
				require.Len(t, request.Items, 2)
				allow := &v1.CheckBulkPermissionsPair{Request: request.Items[0], Response: &v1.CheckBulkPermissionsPair_Item{Item: &v1.CheckBulkPermissionsResponseItem{Permissionship: v1.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION}}}
				deny := &v1.CheckBulkPermissionsPair{Request: request.Items[1], Response: &v1.CheckBulkPermissionsPair_Item{Item: &v1.CheckBulkPermissionsResponseItem{Permissionship: v1.CheckPermissionResponse_PERMISSIONSHIP_NO_PERMISSION}}}
				response := &v1.CheckBulkPermissionsResponse{Pairs: []*v1.CheckBulkPermissionsPair{deny, allow}}
				switch mode {
				case "missing":
					response.Pairs = response.Pairs[:1]
				case "duplicate":
					response.Pairs[0] = allow
				case "foreign", "wrong_actor", "wrong_kind", "wrong_action":
					allow.Request = &v1.CheckBulkPermissionsRequestItem{Resource: &v1.ObjectReference{ObjectType: "scope", ObjectId: "allowed"}, Permission: "read_metadata", Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: "user", ObjectId: testActor.ID.String()}}}
					if mode == "foreign" {
						allow.Request.Resource.ObjectId = "foreign"
					} else if mode == "wrong_kind" {
						allow.Request.Subject.Object.ObjectType = "leta"
					} else if mode == "wrong_actor" {
						allow.Request.Subject.Object.ObjectId = "other"
					} else {
						allow.Request.Permission = "write"
					}
				case "no_result":
					allow.Response = nil
				case "item_error", "invalid_error":
					code := codes.Unavailable
					if mode == "invalid_error" {
						code = codes.OK
					}
					allow.Response = &v1.CheckBulkPermissionsPair_Error{Error: status.New(code, "dependency unavailable").Proto()}
				case "outage":
					return nil, status.Error(codes.Unavailable, "graph unavailable")
				case "nil":
					return nil, nil
				}
				return response, nil
			}}
			allowed, err := BulkCheck(t.Context(), client, testActor, ScopeReadMetadata, resources)
			if mode == "reordered" {
				require.NoError(t, err)
				require.Equal(t, []bool{true, false}, allowed)
			} else {
				require.Error(t, err)
				require.Nil(t, allowed, "never publish partial allows from an invalid/failed batch")
			}
		})
	}
}
