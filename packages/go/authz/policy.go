package authz

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"slices"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"google.golang.org/protobuf/proto"
)

var ErrInvalidPolicy = errors.New("invalid built-in authorization policy")
var ErrPolicyMismatch = errors.New("authorization role policy differs from the expected contract")

// ParseRolePolicy reads deployment-owned capabilities, never an application role evaluator.
func ParseRolePolicy(data []byte) ([]*v1.Relationship, error) {
	var roles map[string][]Action
	if err := json.Unmarshal(data, &roles); err != nil || len(roles) != 3 {
		return nil, ErrInvalidPolicy
	}
	var relationships []*v1.Relationship
	for _, role := range []string{"owner", "editor", "viewer"} {
		actions := slices.Clone(roles[role])
		if len(actions) == 0 {
			return nil, ErrInvalidPolicy
		}
		slices.Sort(actions)
		for i, action := range actions {
			if (!action.Valid("workspace") && !action.Valid("filesystem") && !action.Valid("quota_bucket")) || (i > 0 && action == actions[i-1]) {
				return nil, ErrInvalidPolicy
			}
			relationships = append(relationships, &v1.Relationship{
				Resource: &v1.ObjectReference{ObjectType: "role", ObjectId: role}, Relation: string(action),
				Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: "user", ObjectId: "*"}},
			})
		}
	}
	return relationships, nil
}

// InitializeRolePolicy runs with deployment writers fenced, as does schema initialization.
// Only role capability tuples are replaced; memberships and resource bindings are untouched.
func InitializeRolePolicy(ctx context.Context, client v1.PermissionsServiceClient, expected []*v1.Relationship) error {
	updates, err := rolePolicyChanges(ctx, client, expected)
	if err != nil {
		return err
	}
	if len(updates) > 0 {
		if _, err = client.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: updates}); err != nil {
			return err
		}
	}
	return VerifyRolePolicy(ctx, client, expected)
}

func VerifyRolePolicy(ctx context.Context, client v1.PermissionsServiceClient, expected []*v1.Relationship) error {
	updates, err := rolePolicyChanges(ctx, client, expected)
	if err != nil {
		return err
	}
	if len(updates) > 0 {
		return ErrPolicyMismatch
	}
	return nil
}

func rolePolicyChanges(ctx context.Context, client v1.PermissionsServiceClient, expected []*v1.Relationship) ([]*v1.RelationshipUpdate, error) {
	if len(expected) == 0 {
		return nil, ErrInvalidPolicy
	}
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	stream, err := client.ReadRelationships(ctx, &v1.ReadRelationshipsRequest{
		Consistency: fullyConsistent(), RelationshipFilter: &v1.RelationshipFilter{ResourceType: "role"}, OptionalLimit: 1000,
	})
	if err != nil {
		return nil, err
	}
	var actual []*v1.Relationship
	for {
		response, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, err
		}
		actual = append(actual, response.Relationship)
		if len(actual) >= 1000 {
			return nil, ErrPolicyMismatch
		}
	}
	var updates []*v1.RelationshipUpdate
	for _, relationship := range actual {
		if !slices.ContainsFunc(expected, func(want *v1.Relationship) bool { return proto.Equal(relationship, want) }) {
			updates = append(updates, &v1.RelationshipUpdate{Operation: v1.RelationshipUpdate_OPERATION_DELETE, Relationship: relationship})
		}
	}
	for _, relationship := range expected {
		if !slices.ContainsFunc(actual, func(have *v1.Relationship) bool { return proto.Equal(relationship, have) }) {
			updates = append(updates, &v1.RelationshipUpdate{Operation: v1.RelationshipUpdate_OPERATION_TOUCH, Relationship: relationship})
		}
	}
	if len(updates) > 1000 {
		return nil, ErrPolicyMismatch
	}
	return updates, nil
}
