package workspace

import (
	"context"
	"crypto/sha256"
	"errors"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/authz"
	accountclient "github.com/qninhdt/openlet/packages/go/clients/account"
	letfsclient "github.com/qninhdt/openlet/packages/go/clients/letfs"
)

type UserSummary = accountclient.Summary
type Accounts interface {
	Summaries(context.Context, []uuid.UUID) (map[uuid.UUID]UserSummary, error)
	VerifiedEmails(context.Context, uuid.UUID) ([]string, error)
}
type StorageClient interface {
	CreateStorage(context.Context, letfsclient.Storage) (letfsclient.Storage, error)
	ReleaseProvisioning(context.Context, letfsclient.Storage) error
	FreezeBucket(context.Context, uuid.UUID) error
	ListFilesystems(context.Context, uuid.UUID, uuid.UUID) ([]uuid.UUID, error)
	DeleteFilesystem(context.Context, uuid.UUID) (bool, error)
	CompleteBucket(context.Context, uuid.UUID) error
}
type Service struct {
	Store        *Store
	User         Accounts
	Storage      StorageClient
	StartCreate  func(context.Context, CreateInput) (Workspace, error)
	StartInitial func(context.Context, CreateInput) (Workspace, error)
	Mutate       func(context.Context, Mutation) (Workspace, error)
}

type Mutation struct {
	Kind           string
	WorkspaceID    uuid.UUID
	ActorID        uuid.UUID
	TargetID       uuid.UUID
	Key            uuid.UUID
	Revision       string
	Role           string
	Remove         bool
	Update         UpdateInput
	InvitationHash [32]byte
}
type PreparedMutation struct {
	Command       Mutation
	PreviousOwner uuid.UUID
}
type Provisioning struct {
	Workspace Workspace
	Storage   Storage
}
type EnrichedMember struct {
	User UserSummary `json:"user"`
	Role string      `json:"role"`
}
type Membership struct {
	WorkspaceID uuid.UUID   `json:"workspace_id"`
	User        UserSummary `json:"user"`
	Role        string      `json:"role"`
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

func (s *Service) EnsureInitial(ctx context.Context, in CreateInput) (Workspace, bool, error) {
	if in.ActorID != in.Key {
		return Workspace{}, false, Fault{"VALIDATION"}
	}
	if in.ActorID == uuid.Nil {
		return Workspace{}, false, Fault{"VALIDATION"}
	}
	if err := ValidateName(in.Name); err != nil {
		return Workspace{}, false, err
	}
	value, found, err := s.Store.FindInitialCreation(ctx, in)
	if err != nil {
		return value, false, err
	}
	if !found {
		value, err = s.StartInitial(ctx, in)
	}
	if err != nil {
		return value, false, err
	}
	switch value.Status {
	case "active":
		return value, true, nil
	case "provisioning":
		return value, false, nil
	default:
		return value, false, Fault{"STATE_CONFLICT"}
	}
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
		allowed, err := authz.BulkCheck(check, s.Store.Graph, actor.String(), authz.WorkspaceRead, resources)
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
	if _, err := s.Store.Authorize(ctx, ws, actor, authz.MemberRead); err != nil {
		return nil, nil, err
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
	profiles, err := s.User.Summaries(ctx, ids)
	if err != nil {
		return nil, nil, err
	}
	out := make([]EnrichedMember, 0, len(items))
	for _, item := range items {
		out = append(out, EnrichedMember{User: profiles[item.UserID], Role: item.Role})
	}
	return out, next, nil
}

func (s *Service) Invitations(ctx context.Context, ws, actor, after uuid.UUID, limit int) ([]Invitation, *uuid.UUID, error) {
	if _, err := s.Store.Authorize(ctx, ws, actor, authz.InvitationRead); err != nil {
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

func (s *Service) Update(ctx context.Context, ws, actor uuid.UUID, revision string, in UpdateInput) (Workspace, error) {
	if in.OwnerID != nil {
		return s.Mutate(ctx, Mutation{Kind: "update", WorkspaceID: ws, ActorID: actor, Revision: revision, Update: in})
	}
	return s.Store.Update(ctx, ws, actor, revision, in, MutationReceipt{})
}

func (s *Service) ChangeMember(ctx context.Context, ws, actor, target uuid.UUID, revision, role string, remove bool) error {
	_, err := s.Mutate(ctx, Mutation{Kind: "member", WorkspaceID: ws, ActorID: actor, TargetID: target, Role: role, Remove: remove, Revision: revision})
	return err
}

func (s *Service) Invite(ctx context.Context, ws, actor uuid.UUID, email, role string) (Invitation, string, error) {
	return s.Store.Invite(ctx, ws, actor, email, role)
}

func (s *Service) RevokeInvitation(ctx context.Context, ws, actor, id uuid.UUID) error {
	return s.Store.RevokeInvite(ctx, ws, actor, id)
}

func (s *Service) Delete(ctx context.Context, ws, actor uuid.UUID, revision string) (Workspace, error) {
	return s.Mutate(ctx, Mutation{Kind: "delete", WorkspaceID: ws, ActorID: actor, Revision: revision})
}

func (s *Service) AcceptInvitation(ctx context.Context, actor uuid.UUID, token string) (Membership, error) {
	if len(token) != 43 {
		return Membership{}, Fault{"INVITATION_INVALID"}
	}
	hash := sha256.Sum256([]byte(token))
	ws, err := s.Store.InvitationWorkspace(ctx, hash)
	if err != nil {
		return Membership{}, err
	}
	if _, err = s.Mutate(ctx, Mutation{Kind: "invite", WorkspaceID: ws, ActorID: actor, InvitationHash: hash}); err != nil {
		return Membership{}, err
	}
	value, err := s.Store.Authorize(ctx, ws, actor, authz.MemberRead)
	if err != nil {
		return Membership{}, err
	}
	profiles, err := s.User.Summaries(ctx, []uuid.UUID{actor})
	return Membership{WorkspaceID: ws, User: profiles[actor], Role: value.Role}, err
}

func (s *Service) Prepare(ctx context.Context, in CreateInput) (Provisioning, error) {
	value, err := s.Store.EnsureWorkspace(ctx, in)
	if err != nil {
		return Provisioning{}, err
	}
	storage, err := s.Store.ReserveStorage(ctx, value.ID)
	if err != nil {
		return Provisioning{}, err
	}
	if err = s.Store.InitializeRelationships(ctx, s.Store.Graph, value.ID); err != nil {
		return Provisioning{}, err
	}
	return Provisioning{Workspace: value, Storage: storage}, nil
}
func (s *Service) Complete(ctx context.Context, storage Storage, in CreateInput) error {
	if err := s.Store.PublishActivationRelationships(ctx, s.Store.Graph, storage.WorkspaceID); err != nil {
		return err
	}
	if err := s.Store.Activate(ctx, storage); err != nil {
		return err
	}
	clientStorage, err := ToClientStorage(storage)
	if err != nil {
		return err
	}
	if err := s.Storage.ReleaseProvisioning(ctx, clientStorage); err != nil {
		return err
	}
	return s.Store.CompleteCreation(ctx, in)
}

func ToClientStorage(value Storage) (letfsclient.Storage, error) {
	limit, err := strconv.ParseInt(value.LimitBytes, 10, 64)
	if err != nil || limit < 0 {
		return letfsclient.Storage{}, Fault{"VALIDATION"}
	}
	return letfsclient.Storage{LimitBytes: limit, BucketID: value.BucketID, FilesystemID: value.FilesystemID, RootID: value.RootID}, nil
}

func FromClientStorage(value letfsclient.Storage) Storage {
	return Storage{LimitBytes: strconv.FormatInt(value.LimitBytes, 10), BucketID: value.BucketID, FilesystemID: value.FilesystemID, RootID: value.RootID}
}
func (s *Service) Fail(ctx context.Context, in CreateInput) error {
	value, found, err := s.Store.FindCreation(ctx, in)
	if err != nil || !found {
		return err
	}
	if err = s.Store.Fail(ctx, value.ID); err != nil {
		return err
	}
	return s.Store.PublishStorageRelationships(ctx, s.Store.Graph, value.ID)
}
func (s *Service) PrepareMutation(ctx context.Context, in Mutation) (PreparedMutation, error) {
	out := PreparedMutation{Command: in}
	if in.WorkspaceID == uuid.Nil || in.ActorID == uuid.Nil || in.Key == uuid.Nil {
		return out, Fault{"VALIDATION"}
	}
	switch in.Kind {
	case "member", "invite":
	case "update":
		if in.Update.OwnerID == nil {
			return out, Fault{"VALIDATION"}
		}
		if err := s.Store.DB.QueryRow(ctx, `SELECT user_id FROM workspace_members WHERE workspace_id=$1 AND role='owner'`, in.WorkspaceID).Scan(&out.PreviousOwner); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return out, Fault{"NOT_FOUND"}
			}
			return out, err
		}
	default:
		return out, Fault{"VALIDATION"}
	}
	return out, nil
}
func (s *Service) ApplyMutation(ctx context.Context, in PreparedMutation) (Workspace, error) {
	cmd := in.Command
	receipt := MutationReceipt{Key: cmd.Key, Hash: Fingerprint(in)}
	applied, err := s.Store.MutationApplied(ctx, cmd.ActorID, cmd.WorkspaceID, receipt)
	if err != nil {
		return Workspace{}, err
	}
	if !applied {
		switch cmd.Kind {
		case "member":
			err = s.Store.ChangeMember(ctx, cmd.WorkspaceID, cmd.ActorID, cmd.TargetID, cmd.Role, cmd.Remove, cmd.Revision, receipt)
		case "update":
			_, err = s.Store.Update(ctx, cmd.WorkspaceID, cmd.ActorID, cmd.Revision, cmd.Update, receipt)
		case "invite":
			var emails []string
			emails, err = s.User.VerifiedEmails(ctx, cmd.ActorID)
			if err == nil {
				_, err = s.Store.AcceptInvite(ctx, cmd.ActorID, cmd.InvitationHash, emails, receipt)
			}
		default:
			return Workspace{}, Fault{"VALIDATION"}
		}
		if err != nil {
			applied, checkErr := s.Store.MutationApplied(ctx, cmd.ActorID, cmd.WorkspaceID, receipt)
			if checkErr != nil {
				return Workspace{}, checkErr
			}
			if !applied {
				return Workspace{}, err
			}
		}
	}
	affected := []uuid.UUID{cmd.TargetID}
	if cmd.Kind == "update" {
		affected = []uuid.UUID{in.PreviousOwner, *cmd.Update.OwnerID}
	}
	if cmd.Kind == "invite" {
		affected = []uuid.UUID{cmd.ActorID}
	}
	if err = s.Store.WriteMemberRelationships(ctx, s.Store.Graph, cmd.WorkspaceID, affected...); err != nil {
		return Workspace{}, err
	}
	if err = s.Store.CompleteMutation(ctx, cmd.ActorID, receipt); err != nil {
		return Workspace{}, err
	}
	if cmd.Kind == "member" && cmd.Remove && cmd.TargetID == cmd.ActorID {
		return Workspace{ID: cmd.WorkspaceID}, nil
	}
	return s.Store.Get(ctx, cmd.WorkspaceID, cmd.ActorID)
}
func (s *Service) BeginDeletion(ctx context.Context, in DeleteInput) (Workspace, error) {
	value, err := s.Store.BeginDeletion(ctx, in)
	if err == nil {
		err = s.Store.PublishStorageRelationships(ctx, s.Store.Graph, value.ID)
	}
	return value, err
}
func (s *Service) CompleteDeletion(ctx context.Context, id uuid.UUID) error {
	if err := s.Store.CompleteDeletion(ctx, id); err != nil {
		return err
	}
	return s.Store.DeleteMemberRelationships(ctx, s.Store.Graph, id)
}
