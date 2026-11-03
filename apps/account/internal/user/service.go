package user

import (
	"context"
	"errors"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type Clerk interface {
	VerifiedEmails(context.Context, string) ([]string, error)
	PublishUserID(context.Context, string, string) error
}

type Workspace interface {
	EnsureInitial(context.Context, uuid.UUID) (uuid.UUID, bool, error)
}

type Service struct {
	Store           *Store
	Graph           v1.PermissionsServiceClient
	Clerk           Clerk
	Workspace       Workspace
	StartOnboarding func(context.Context, string) (Onboarding, error)
}

func (s *Service) GetOnboarding(ctx context.Context, subject string) (Onboarding, error) {
	return s.Store.Onboarding(ctx, subject)
}

func (s *Service) Onboard(ctx context.Context, subject string) (Onboarding, bool, error) {
	value, err := s.Store.Onboarding(ctx, subject)
	if err == nil && value.Status != "provisioning" {
		return value, false, nil
	}
	var fault Fault
	if err != nil && (!errors.As(err, &fault) || fault.Code != "NOT_FOUND") {
		return value, false, err
	}
	value, err = s.StartOnboarding(ctx, subject)
	if err != nil {
		existing, lookupErr := s.Store.Onboarding(ctx, subject)
		if lookupErr == nil && existing.Status != "provisioning" {
			return existing, false, nil
		}
	}
	return value, true, err
}

func (s *Service) authorize(ctx context.Context, actor uuid.UUID, action authz.Action) error {
	if s.Graph == nil {
		return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "authorization unavailable")
	}
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	allowed, err := authz.Check(ctx, s.Graph, actor.String(), action, authz.Resource{Type: "account", ID: actor.String()})
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
		err = s.authorize(ctx, actor, authz.AccountRead)
	}
	return value, err
}

func (s *Service) UpdateProfile(ctx context.Context, actor uuid.UUID, name, avatar *string) (Profile, error) {
	if _, err := s.Store.Profile(ctx, actor); err != nil {
		return Profile{}, err
	}
	if err := s.authorize(ctx, actor, authz.AccountUpdate); err != nil {
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
	return s.Clerk.VerifiedEmails(ctx, subject)
}

func (s *Service) EnsureUser(ctx context.Context, subject string) (Onboarding, error) {
	value, err := s.Store.EnsureUser(ctx, subject)
	if err == nil {
		err = s.Store.SyncRelationships(ctx, s.Graph, value.UserID)
	}
	return value, err
}
