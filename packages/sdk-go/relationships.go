package sdk

import (
	"context"
	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"google.golang.org/grpc/metadata"
)

func Object(kind, id string) *v1.ObjectReference {
	return &v1.ObjectReference{ObjectType: kind, ObjectId: id}
}
func Subject(a Actor) *v1.SubjectReference { return &v1.SubjectReference{Object: Object(a.Type, a.ID)} }
func Relation(kind, id, relation, subjectKind, subjectID, subjectRelation string) *v1.Relationship {
	return &v1.Relationship{Resource: Object(kind, id), Relation: relation, Subject: &v1.SubjectReference{Object: Object(subjectKind, subjectID), OptionalRelation: subjectRelation}}
}
func Touch(r *v1.Relationship) *v1.RelationshipUpdate {
	return &v1.RelationshipUpdate{Operation: v1.RelationshipUpdate_OPERATION_TOUCH, Relationship: r}
}
func Delete(r *v1.Relationship) *v1.RelationshipUpdate {
	return &v1.RelationshipUpdate{Operation: v1.RelationshipUpdate_OPERATION_DELETE, Relationship: r}
}
func Consistency(ctx context.Context) *v1.Consistency {
	md, _ := metadata.FromIncomingContext(ctx)
	if tokens := md.Get("x-openlet-zed-token"); len(tokens) == 1 {
		return &v1.Consistency{Requirement: &v1.Consistency_AtLeastAsFresh{AtLeastAsFresh: &v1.ZedToken{Token: tokens[0]}}}
	}
	return &v1.Consistency{Requirement: &v1.Consistency_MinimizeLatency{MinimizeLatency: true}}
}
