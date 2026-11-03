package workspace

import (
	"context"
	"errors"
	"io"
	"strings"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// CleanupRelationships removes abandoned staging without deleting a published grant.
func (s *Store) CleanupRelationships(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID) error {
	if id == uuid.Nil {
		return Fault{"VALIDATION"}
	}
	var cursor *v1.Cursor
	for {
		groups, next, count, err := relationshipGroups(ctx, graph, id, cursor)
		if err != nil {
			return err
		}
		// A current canonical group may be between staging and publication.
		var revision, lifecycle string
		if err := s.DB.QueryRow(ctx, `SELECT revision::text,status FROM workspaces WHERE id=$1`, id).Scan(&revision, &lifecycle); err != nil {
			return err
		}
		current := id.String() + "/" + revision + "/" + lifecycle + "/"
		for group := range groups {
			if strings.HasPrefix(group, current) {
				continue
			}
			request := &v1.DeleteRelationshipsRequest{
				RelationshipFilter: &v1.RelationshipFilter{ResourceType: "role_grant", OptionalResourceId: group},
				OptionalPreconditions: []*v1.Precondition{{Operation: v1.Precondition_OPERATION_MUST_NOT_MATCH, Filter: &v1.RelationshipFilter{
					ResourceType: "workspace", OptionalResourceId: id.String(), OptionalRelation: "grant",
					OptionalSubjectFilter: &v1.SubjectFilter{SubjectType: "role_grant", OptionalSubjectId: group},
				}}},
				OptionalLimit: 1000, OptionalAllowPartialDeletions: true,
			}
			for {
				response, err := graph.DeleteRelationships(ctx, request)
				if status.Code(err) == codes.FailedPrecondition {
					break
				}
				if err != nil {
					return err
				}
				if response.DeletionProgress == v1.DeleteRelationshipsResponse_DELETION_PROGRESS_COMPLETE {
					break
				}
				if response.DeletionProgress != v1.DeleteRelationshipsResponse_DELETION_PROGRESS_PARTIAL || response.RelationshipsDeletedCount == 0 {
					return Fault{"STATE_CONFLICT"}
				}
			}
		}
		if count < 1000 {
			return nil
		}
		cursor = next
	}
}

func relationshipGroups(ctx context.Context, graph v1.PermissionsServiceClient, id uuid.UUID, cursor *v1.Cursor) (map[string]bool, *v1.Cursor, int, error) {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()
	stream, err := graph.ReadRelationships(ctx, &v1.ReadRelationshipsRequest{
		Consistency:        &v1.Consistency{Requirement: &v1.Consistency_FullyConsistent{FullyConsistent: true}},
		RelationshipFilter: &v1.RelationshipFilter{ResourceType: "role_grant", OptionalResourceIdPrefix: id.String() + "/"},
		OptionalLimit:      1000, OptionalCursor: cursor,
	})
	if err != nil {
		return nil, nil, 0, err
	}
	groups := make(map[string]bool)
	count := 0
	for {
		response, err := stream.Recv()
		if errors.Is(err, io.EOF) {
			return groups, cursor, count, nil
		}
		if err != nil {
			return nil, nil, 0, err
		}
		groups[response.Relationship.Resource.ObjectId] = true
		cursor = response.AfterResultCursor
		count++
	}
}
