package workspace

import (
	"context"
	"crypto/sha256"
	"errors"
	"github.com/qninhdt/openlet/packages/go/identity"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/authz"
	accountclient "github.com/qninhdt/openlet/packages/go/clients/account"
	letaclient "github.com/qninhdt/openlet/packages/go/clients/leta"
	letfsclient "github.com/qninhdt/openlet/packages/go/clients/letfs"
)

type UserSummary = accountclient.Summary
type Users interface {
	Summaries(context.Context, []uuid.UUID) (map[uuid.UUID]UserSummary, error)
	VerifiedEmails(context.Context, uuid.UUID) ([]string, error)
}
type LetaResources interface {
	GetBinding(context.Context, uuid.UUID) (letaclient.Binding, error)
}
type ScopeStorage interface {
	ListScopes(context.Context, uuid.UUID, int32, *string) (letfsclient.ScopePage, error)
}
type HomeStorage interface {
	CreateScopes(context.Context, uuid.UUID, uuid.UUID, []uuid.UUID, bool, bool) ([]letfsclient.Scope, error)
}
type Service struct {
	Store       *Store
	Users       Users
	Letas       LetaResources
	Storage     ScopeStorage
	Homes       HomeStorage
	StartCreate func(context.Context, CreateInput) (Workspace, error)
	Mutate      func(context.Context, Mutation) (Workspace, error)
}
type Mutation struct {
	Kind            string
	WorkspaceID     uuid.UUID
	ActorID         uuid.UUID
	TargetID        uuid.UUID
	Key             uuid.UUID
	Role            string
	Remove          bool
	PersonalScopeID uuid.UUID
	ExistingScope   bool
	FilesystemID    uuid.UUID
	InvitationHash  [32]byte
	ScopeID         uuid.UUID
	ScopeRole       string
	Revoke          bool
	TargetKind      identity.ActorKind
	PersonalOwnerID uuid.UUID
}
type EnrichedMember struct {
	User            UserSummary `json:"user"`
	Role            string      `json:"role"`
	PersonalScopeID uuid.UUID   `json:"personal_scope_id"`
}
type Membership struct {
	WorkspaceID     uuid.UUID   `json:"workspace_id"`
	User            UserSummary `json:"user"`
	Role            string      `json:"role"`
	PersonalScopeID uuid.UUID   `json:"personal_scope_id"`
}

func (s *Service) Create(ctx context.Context, in CreateInput) (Workspace, error) {
	if in.ActorID == uuid.Nil || in.Key == uuid.Nil || in.ActorID == in.Key {
		return Workspace{}, Fault{"VALIDATION"}
	}
	if err := ValidateName(in.Name); err != nil {
		return Workspace{}, err
	}
	value, found, err := s.Store.FindCreation(ctx, in)
	if err != nil || found {
		return value, err
	}
	value, err = s.StartCreate(ctx, in)
	if err != nil {
		existing, found, lookupErr := s.Store.FindCreation(ctx, in)
		if lookupErr != nil {
			return Workspace{}, lookupErr
		}
		if found {
			return existing, nil
		}
	}
	return value, err
}

func (s *Service) List(ctx context.Context, actor, after uuid.UUID, limit int) ([]Workspace, *uuid.UUID, error) {
	items, err := s.Store.List(ctx, actor, after, limit)
	if err != nil {
		return nil, nil, err
	}
	var next *uuid.UUID
	if len(items) == limit {
		id := items[len(items)-1].ID
		next = &id
	}
	if len(items) > 0 {
		resources := make([]authz.Resource, len(items))
		for i, item := range items {
			resources[i] = authz.Resource{Type: "workspace", ID: item.ID.String()}
		}
		check, cancel := context.WithTimeout(ctx, 2*time.Second)
		defer cancel()
		allowed, err := authz.BulkCheck(check, s.Store.Graph, identity.Actor{Kind: identity.User, ID: actor}, authz.WorkspaceRead, resources)
		if err != nil {
			return nil, nil, err
		}
		visible := items[:0]
		for i, item := range items {
			if allowed[i] {
				visible = append(visible, item)
			}
		}
		items = visible
	}
	return items, next, nil
}

func (s *Service) Get(ctx context.Context, workspaceID, actorID uuid.UUID) (Workspace, error) {
	return s.Store.Authorize(ctx, workspaceID, actorID, authz.WorkspaceRead)
}

func (s *Service) Members(ctx context.Context, ws, actor, after uuid.UUID, limit int) ([]EnrichedMember, *uuid.UUID, error) {
	if _, err := s.Store.Authorize(ctx, ws, actor, authz.WorkspaceRead); err != nil {
		return nil, nil, err
	}
	return s.enrichedMembers(ctx, ws, after, limit)
}

func (s *Service) enrichedMembers(ctx context.Context, ws, after uuid.UUID, limit int) ([]EnrichedMember, *uuid.UUID, error) {
	if limit < 1 || limit > 100 {
		return nil, nil, Fault{"VALIDATION"}
	}
	items, err := s.Store.Members(ctx, ws, after, limit+1)
	if err != nil {
		return nil, nil, err
	}
	var next *uuid.UUID
	if len(items) > limit {
		items = items[:limit]
		id := items[len(items)-1].UserID
		next = &id
	}
	ids := make([]uuid.UUID, len(items))
	for i, item := range items {
		ids[i] = item.UserID
	}
	if len(ids) == 0 {
		return []EnrichedMember{}, next, nil
	}
	profiles, err := s.Users.Summaries(ctx, ids)
	if err != nil {
		return nil, nil, err
	}
	out := make([]EnrichedMember, 0, len(items))
	for _, item := range items {
		profile, ok := profiles[item.UserID]
		if !ok || profile.ID != item.UserID {
			return nil, nil, unavailable()
		}
		out = append(out, EnrichedMember{User: profile, Role: item.Role, PersonalScopeID: item.PersonalScopeID})
	}
	return out, next, nil
}

func (s *Service) Invitations(ctx context.Context, ws, actor, after uuid.UUID, limit int) ([]Invitation, *uuid.UUID, error) {
	if _, err := s.Store.Authorize(ctx, ws, actor, authz.WorkspaceManageMembers); err != nil {
		return nil, nil, err
	}
	items, err := s.Store.Invitations(ctx, ws, after, limit+1)
	if err != nil {
		return nil, nil, err
	}
	var next *uuid.UUID
	if len(items) > limit {
		items = items[:limit]
		id := items[len(items)-1].ID
		next = &id
	}
	return items, next, nil
}

func (s *Service) Update(ctx context.Context, ws, actor uuid.UUID, in UpdateInput) (Workspace, error) {
	return s.Store.Update(ctx, ws, actor, in)
}
func (s *Service) ChangeMember(ctx context.Context, ws, actor, target uuid.UUID, role string, remove bool) error {
	value, err := s.Store.Get(ctx, ws, actor)
	if err != nil {
		return err
	}
	if err = value.checkActive(); err != nil {
		return err
	}
	if actor != target || !remove {
		if _, err = s.Store.Authorize(ctx, ws, actor, authz.WorkspaceManageMembers); err != nil {
			return err
		}
	}
	member, err := s.Store.Member(ctx, ws, target)
	if err != nil {
		return err
	}
	if member.Role == "owner" {
		return Fault{"FORBIDDEN"}
	}
	if !remove && role != "admin" && role != "member" {
		return Fault{"VALIDATION"}
	}
	_, err = s.Mutate(ctx, Mutation{Kind: "member", WorkspaceID: ws, ActorID: actor, TargetID: target, Role: role, Remove: remove, PersonalScopeID: member.PersonalScopeID})
	return err
}
func (s *Service) Invite(ctx context.Context, ws, actor uuid.UUID, email, role string) (Invitation, string, error) {
	return s.Store.Invite(ctx, ws, actor, email, role)
}
func (s *Service) RevokeInvitation(ctx context.Context, ws, actor, id uuid.UUID) error {
	return s.Store.RevokeInvite(ctx, ws, actor, id)
}
func (s *Service) Delete(ctx context.Context, ws, actor uuid.UUID) (Workspace, error) {
	if _, err := s.Store.Authorize(ctx, ws, actor, authz.WorkspaceDelete); err != nil {
		return Workspace{}, err
	}
	return s.Mutate(ctx, Mutation{Kind: "delete", WorkspaceID: ws, ActorID: actor})
}
func (s *Service) AddUser(ctx context.Context, ws, actor, target uuid.UUID, role string) (Workspace, error) {
	if role != "admin" && role != "member" {
		return Workspace{}, Fault{"VALIDATION"}
	}
	value, err := s.Store.Authorize(ctx, ws, actor, authz.WorkspaceManageMembers)
	if err != nil {
		return Workspace{}, err
	}
	if err = value.checkActive(); err != nil {
		return Workspace{}, err
	}
	if _, err = s.Users.Summaries(ctx, []uuid.UUID{target}); err != nil {
		return Workspace{}, err
	}
	input := Mutation{Kind: "add", WorkspaceID: ws, ActorID: actor, TargetID: target, Role: role, FilesystemID: value.FilesystemID, PersonalScopeID: uuid.Must(uuid.NewV7())}
	retained, err := s.Store.Member(ctx, ws, target)
	if err == nil {
		if retained.Role == "owner" {
			return Workspace{}, Fault{"FORBIDDEN"}
		}
		input.PersonalScopeID = retained.PersonalScopeID
		input.ExistingScope = true
	} else {
		var fault Fault
		if !errors.As(err, &fault) || fault.Code != "NOT_FOUND" {
			return Workspace{}, err
		}
	}
	return s.Mutate(ctx, input)
}
func (s *Service) AcceptInvitation(ctx context.Context, actor uuid.UUID, token string) (Membership, error) {
	if len(token) != 43 {
		return Membership{}, Fault{"VALIDATION"}
	}
	hash := sha256.Sum256([]byte(token))
	emails, err := s.Users.VerifiedEmails(ctx, actor)
	if err != nil {
		return Membership{}, err
	}
	ws, role, err := s.Store.AdmitInvitation(ctx, actor, hash, emails)
	if err != nil {
		return Membership{}, err
	}
	var filesystemID uuid.UUID
	if err = s.Store.DB.QueryRow(ctx, `SELECT filesystem_id FROM workspaces WHERE id=$1 AND status='active'`, ws).Scan(&filesystemID); err != nil {
		return Membership{}, err
	}
	input := Mutation{Kind: "join", WorkspaceID: ws, ActorID: actor, TargetID: actor, Role: role, InvitationHash: hash, FilesystemID: filesystemID, PersonalScopeID: uuid.Must(uuid.NewV7())}
	member, err := s.Store.Member(ctx, ws, actor)
	if err == nil {
		input.PersonalScopeID = member.PersonalScopeID
		input.ExistingScope = true
	} else {
		var fault Fault
		if !errors.As(err, &fault) || fault.Code != "NOT_FOUND" {
			return Membership{}, err
		}
	}
	if _, err = s.Mutate(ctx, input); err != nil {
		return Membership{}, err
	}
	member, err = s.Store.Member(ctx, ws, actor)
	if err != nil {
		return Membership{}, err
	}
	profiles, err := s.Users.Summaries(ctx, []uuid.UUID{actor})
	if err != nil {
		return Membership{}, err
	}
	return Membership{WorkspaceID: ws, User: profiles[actor], Role: member.Role, PersonalScopeID: member.PersonalScopeID}, nil
}
func (s *Service) SaveWorkspace(ctx context.Context, in Creation) (Workspace, error) {
	value, err := s.Store.SaveWorkspace(ctx, in)
	if err != nil {
		return value, err
	}
	if err = s.Store.PublishStorageRelationships(ctx, s.Store.Graph, value.ID); err != nil {
		return value, err
	}
	if err = s.Store.WriteMemberRelationships(ctx, s.Store.Graph, value.ID, true, in.Input.ActorID); err != nil {
		return value, err
	}
	if err = s.Store.CompleteMutation(ctx, in.Input.ActorID, MutationReceipt{Key: in.Input.Key, Hash: Fingerprint(in.Input)}); err != nil {
		return value, err
	}
	return value, nil
}
