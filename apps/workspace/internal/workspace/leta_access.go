package workspace

import (
	"context"
	"errors"
	"io"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/authz"
	letaclient "github.com/qninhdt/openlet/packages/go/clients/leta"
	"github.com/qninhdt/openlet/packages/go/identity"
)

func (s *Store) resourceRecord(ctx context.Context, ws uuid.UUID) (Workspace, error) {
	var value Workspace
	err := s.DB.QueryRow(ctx, `SELECT id,name,filesystem_id,shared_scope_id,status FROM workspaces WHERE id=$1`, ws).
		Scan(&value.ID, &value.Name, &value.FilesystemID, &value.SharedScopeID, &value.Status)
	if errors.Is(err, pgx.ErrNoRows) {
		return value, Fault{"NOT_FOUND"}
	}
	return value, err
}

func (s *Service) ResourceWorkspace(ctx context.Context, ws uuid.UUID, actor identity.Actor) (Workspace, error) {
	value, _, err := s.resourceWorkspace(ctx, ws, actor)
	return value, err
}

// Cleanup reads stay outside Workflow command locks and reveal no member or content data.
func (s *Service) CleanupWorkspace(ctx context.Context, ws, root uuid.UUID) (Workspace, error) {
	if ws == uuid.Nil || root == uuid.Nil {
		return Workspace{}, Fault{"VALIDATION"}
	}
	value, err := s.Store.resourceRecord(ctx, ws)
	if err != nil {
		return Workspace{}, err
	}
	if value.Status != "deleting" && value.Status != "deleted" {
		return Workspace{}, Fault{"FORBIDDEN"}
	}
	if _, err = s.letaBinding(ctx, ws, root); err != nil {
		return Workspace{}, err
	}
	value.Name = ""
	return value, nil
}

func (s *Service) ResourceMembers(ctx context.Context, ws uuid.UUID, actor identity.Actor, after uuid.UUID, limit int) ([]EnrichedMember, *uuid.UUID, error) {
	if _, _, err := s.resourceWorkspace(ctx, ws, actor); err != nil {
		return nil, nil, err
	}
	return s.enrichedMembers(ctx, ws, after, limit)
}

func (s *Store) hasRelationship(ctx context.Context, kind string, id uuid.UUID, relation, subjectKind string, subject uuid.UUID) (bool, error) {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	stream, err := s.Graph.ReadRelationships(ctx, &v1.ReadRelationshipsRequest{
		Consistency: &v1.Consistency{Requirement: &v1.Consistency_FullyConsistent{FullyConsistent: true}},
		RelationshipFilter: &v1.RelationshipFilter{ResourceType: kind, OptionalResourceId: id.String(), OptionalRelation: relation,
			OptionalSubjectFilter: &v1.SubjectFilter{SubjectType: subjectKind, OptionalSubjectId: subject.String(), OptionalRelation: &v1.SubjectFilter_RelationFilter{Relation: ""}}}, OptionalLimit: 1})
	if err != nil {
		return false, err
	}
	_, err = stream.Recv()
	if errors.Is(err, io.EOF) {
		return false, nil
	}
	return err == nil, err
}

func (s *Service) homeAdmission(ctx context.Context, in Mutation) (Workspace, letaclient.Binding, error) {
	if in.Kind != "leta-home" || in.WorkspaceID == uuid.Nil || in.ActorID == uuid.Nil || in.TargetID == uuid.Nil || in.ScopeID == uuid.Nil || in.Key == uuid.Nil {
		return Workspace{}, letaclient.Binding{}, Fault{"VALIDATION"}
	}
	binding, err := s.letaBinding(ctx, in.WorkspaceID, in.TargetID)
	if err != nil {
		return Workspace{}, binding, err
	}
	if binding.CreatedByUserID != in.ActorID || binding.HomeScopeID != in.ScopeID {
		return Workspace{}, binding, Fault{"FORBIDDEN"}
	}
	if binding.Status != "initializing" && binding.Status != "active" {
		return Workspace{}, binding, Fault{"STATE_CONFLICT"}
	}
	value, err := s.Store.Authorize(ctx, in.WorkspaceID, in.ActorID, authz.WorkspaceCreateLeta)
	if err != nil {
		return value, binding, err
	}
	if err = value.checkActive(); err != nil {
		return value, binding, err
	}
	for relation, subject := range map[string]uuid.UUID{"creator": in.ActorID, "workspace": in.WorkspaceID} {
		kind := "user"
		if relation == "workspace" {
			kind = "workspace"
		}
		ok, err := s.Store.hasRelationship(ctx, "leta", in.TargetID, relation, kind, subject)
		if err != nil {
			return value, binding, err
		}
		if !ok {
			return value, binding, Fault{"FORBIDDEN"}
		}
	}
	return value, binding, nil
}

func (s *Service) EnsureLetaHomeAccess(ctx context.Context, in Mutation) (Workspace, error) {
	if _, _, err := s.homeAdmission(ctx, in); err != nil {
		return Workspace{}, err
	}
	if err := s.Store.reserveMutation(ctx, in); err != nil {
		return Workspace{}, err
	}
	return s.Mutate(ctx, in)
}

func (s *Service) ProvisionLetaHome(ctx context.Context, in Mutation) (Workspace, error) {
	ctx, cancel := context.WithTimeout(ctx, 25*time.Second)
	defer cancel()
	value, _, err := s.homeAdmission(ctx, in)
	if err != nil {
		return Workspace{}, err
	}
	if err = s.Store.reserveMutation(ctx, in); err != nil {
		return Workspace{}, err
	}
	if s.Homes == nil {
		return Workspace{}, unavailable()
	}
	scopes, err := s.Homes.CreateScopes(ctx, value.FilesystemID, in.Key, []uuid.UUID{in.ScopeID}, true, true)
	if err != nil {
		return Workspace{}, err
	}
	if len(scopes) != 1 || scopes[0].ID != in.ScopeID || scopes[0].FilesystemID != value.FilesystemID || scopes[0].RootID == uuid.Nil || scopes[0].State != "active" || !scopes[0].AllowBlobFiles || !scopes[0].AllowIndexing {
		return Workspace{}, Fault{"STORAGE_SCOPE_CONFLICT"}
	}
	_, err = s.Store.Graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "scope", in.ScopeID.String(), "home_of", "leta", in.TargetID.String()),
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "scope", in.ScopeID.String(), "editor", "leta", in.TargetID.String()),
		graphUpdate(v1.RelationshipUpdate_OPERATION_TOUCH, "scope", value.SharedScopeID.String(), "editor", "leta", in.TargetID.String()),
	}})
	if err != nil {
		return Workspace{}, err
	}
	err = s.Store.CompleteMutation(ctx, in.ActorID, MutationReceipt{Key: in.Key, Hash: Fingerprint(in)})
	return value, err
}

type PersonalScope struct{ WorkspaceID, FilesystemID, ScopeID, OwnerUserID uuid.UUID }

func (s *Service) ResolvePersonalScope(ctx context.Context, ws, root, owner uuid.UUID) (PersonalScope, error) {
	if owner == uuid.Nil {
		return PersonalScope{}, Fault{"VALIDATION"}
	}
	value, _, err := s.resourceWorkspace(ctx, ws, identity.Actor{Kind: identity.Leta, ID: root})
	if err != nil {
		return PersonalScope{}, err
	}
	member, err := s.Store.Member(ctx, ws, owner)
	if err != nil {
		return PersonalScope{}, err
	}
	if member.Status != "active" {
		return PersonalScope{}, Fault{"NOT_FOUND"}
	}
	return PersonalScope{ws, value.FilesystemID, member.PersonalScopeID, owner}, nil
}

func (s *Service) CleanupLetaAccess(ctx context.Context, ws, root, home uuid.UUID, actor identity.Actor) error {
	if ws == uuid.Nil || root == uuid.Nil || home == uuid.Nil {
		return Fault{"VALIDATION"}
	}
	ctx, cancel := context.WithTimeout(ctx, 90*time.Second)
	defer cancel()
	binding, err := s.letaBinding(ctx, ws, root)
	if err != nil {
		return err
	}
	if binding.HomeScopeID != home {
		return Fault{"FORBIDDEN"}
	}
	if binding.Status != "deleting" && binding.Status != "archived" {
		return Fault{"STATE_CONFLICT"}
	}
	value, err := s.Store.resourceRecord(ctx, ws)
	if err != nil {
		return err
	}
	if actor.Valid() {
		if actor.Kind != identity.User || actor.ID != binding.CreatedByUserID {
			return Fault{"FORBIDDEN"}
		}
	} else if actor != (identity.Actor{}) || (value.Status != "deleting" && value.Status != "deleted") {
		return Fault{"FORBIDDEN"}
	}
	// Workspace finalization follows successful filesystem deletion.
	if value.Status == "deleted" {
		return nil
	}
	if s.Storage == nil {
		return unavailable()
	}
	var cursor *string
	for {
		page, err := s.Storage.ListScopes(ctx, value.FilesystemID, 100, cursor)
		if err != nil {
			return err
		}
		updates := make([]*v1.RelationshipUpdate, 0, 2*len(page.Items))
		for _, scope := range page.Items {
			for _, role := range []string{"viewer", "editor"} {
				updates = append(updates, graphUpdate(v1.RelationshipUpdate_OPERATION_DELETE, "scope", scope.ID.String(), role, "leta", root.String()))
			}
		}
		if len(updates) > 0 {
			if _, err = s.Store.Graph.WriteRelationships(ctx, &v1.WriteRelationshipsRequest{Updates: updates}); err != nil {
				return err
			}
		}
		if page.NextCursor == nil {
			return nil
		}
		cursor = page.NextCursor
	}
}
