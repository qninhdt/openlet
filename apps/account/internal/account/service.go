package account

import (
	"context"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type Clerk interface {
	VerifiedEmails(context.Context, string) ([]string, error)
	PublishAccountIdentity(context.Context, string, string) error
	AccountIdentity(context.Context, string) (string, error)
}

type Service struct {
	Store           *Store
	Graph           v1.PermissionsServiceClient
	Clerk           Clerk
	StartOnboarding func(context.Context, string) (Onboarding, error)
	StartManaged    func(context.Context, ManagedCreation) (Profile, error)
}

func (s *Service) GetOnboarding(ctx context.Context, subject string) (Onboarding, error) {
	published, err := s.Clerk.AccountIdentity(ctx, subject)
	if err != nil {
		return Onboarding{}, err
	}
	if published != "" {
		id, err := uuid.Parse(published)
		if err != nil || id == uuid.Nil {
			return Onboarding{}, Fault{"STATE_CONFLICT"}
		}
		var canonical uuid.UUID
		if err = s.Store.DB.QueryRow(ctx, `SELECT id FROM accounts WHERE clerk_id=$1`, subject).Scan(&canonical); err != nil {
			return Onboarding{}, err
		}
		if id != canonical {
			return Onboarding{}, Fault{"STATE_CONFLICT"}
		}
		return Onboarding{AccountID: id, Status: "active", RefreshSession: true}, nil
	}
	return Onboarding{Status: "pending"}, nil
}

func (s *Service) Onboard(ctx context.Context, subject string) (Onboarding, bool, error) {
	value, err := s.GetOnboarding(ctx, subject)
	if err != nil || value.Status == "active" {
		return value, false, err
	}
	value, err = s.StartOnboarding(ctx, subject)
	return value, true, err
}

func (s *Service) authorize(ctx context.Context, actor, target uuid.UUID, action authz.Action) error {
	if s.Graph == nil {
		return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "authorization unavailable")
	}
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	allowed, err := authz.Check(ctx, s.Graph, actor.String(), action, authz.Resource{Type: "account", ID: target.String()})
	if err != nil {
		return err
	}
	if !allowed {
		return Fault{"FORBIDDEN"}
	}
	return nil
}

func (s *Service) Profile(ctx context.Context, actor uuid.UUID) (Profile, error) {
	value, err := s.Store.Profile(ctx, actor)
	if err == nil {
		err = s.authorize(ctx, actor, actor, authz.AccountRead)
	}
	return value, err
}

func (s *Service) UpdateProfile(ctx context.Context, actor uuid.UUID, name, avatar *string) (Profile, error) {
	if _, err := s.Store.Profile(ctx, actor); err != nil {
		return Profile{}, err
	}
	if err := s.authorize(ctx, actor, actor, authz.AccountUpdate); err != nil {
		return Profile{}, err
	}
	if name == nil && avatar == nil {
		return Profile{}, Fault{"VALIDATION"}
	}
	return s.Store.UpdateProfile(ctx, actor, name, avatar)
}

func (s *Service) VerifiedEmails(ctx context.Context, id uuid.UUID) ([]string, error) {
	subject, err := s.Store.Subject(ctx, id)
	if err != nil {
		return nil, err
	}
	if subject == "" {
		return []string{}, nil
	}
	return s.Clerk.VerifiedEmails(ctx, subject)
}

func (s *Service) EnsureAccount(ctx context.Context, subject string) (Onboarding, error) {
	completed, err := s.GetOnboarding(ctx, subject)
	if err != nil || completed.Status == "active" {
		return completed, err
	}
	id, err := s.Store.EnsureAccount(ctx, subject)
	if err == nil {
		err = s.Store.SyncRelationships(ctx, s.Graph, id)
	}
	return Onboarding{AccountID: id, Status: "pending"}, err
}

func (s *Service) ApplyAccountChange(ctx context.Context, in ManagedCreation) (Profile, error) {
	value, err := s.Store.CreateManaged(ctx, in)
	if err == nil {
		err = s.Store.SyncRelationships(ctx, s.Graph, in.ID)
	}
	return value, err
}
func (s *Service) CreateManaged(ctx context.Context, actor uuid.UUID, name, avatar string) (Profile, error) {
	if actor == uuid.Nil {
		return Profile{}, Fault{"FORBIDDEN"}
	}
	if _, err := s.Store.Profile(ctx, actor); err != nil {
		return Profile{}, err
	}
	if err := validateProfile(&name, &avatar); err != nil {
		return Profile{}, err
	}
	return s.StartManaged(ctx, ManagedCreation{ID: uuid.Must(uuid.NewV7()), OwnerID: actor, DisplayName: name, AvatarURL: avatar})
}
func (s *Service) GetAccount(ctx context.Context, actor, target uuid.UUID) (Profile, error) {
	if err := s.authorize(ctx, actor, target, authz.AccountRead); err != nil {
		return Profile{}, err
	}
	return s.Store.Profile(ctx, target)
}
func (s *Service) UpdateAccount(ctx context.Context, actor, target uuid.UUID, name, avatar *string) (Profile, error) {
	if err := s.authorize(ctx, actor, target, authz.AccountUpdate); err != nil {
		return Profile{}, err
	}
	if name == nil && avatar == nil {
		return Profile{}, Fault{"VALIDATION"}
	}
	return s.Store.UpdateProfile(ctx, target, name, avatar)
}
