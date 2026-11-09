package account

import (
	"context"

	"github.com/google/uuid"
)

type Clerk interface {
	VerifiedEmails(context.Context, string) ([]string, error)
	PublishUserIdentity(context.Context, string, string) error
	UserIdentity(context.Context, string) (string, error)
}

type Service struct {
	Store           *Store
	Clerk           Clerk
	StartOnboarding func(context.Context, string) (Onboarding, error)
}

func (s *Service) GetOnboarding(ctx context.Context, subject string) (Onboarding, error) {
	published, err := s.Clerk.UserIdentity(ctx, subject)
	if err != nil {
		return Onboarding{}, err
	}
	if published != "" {
		id, err := uuid.Parse(published)
		if err != nil || id == uuid.Nil {
			return Onboarding{}, Fault{"STATE_CONFLICT"}
		}
		var canonical uuid.UUID
		if err = s.Store.DB.QueryRow(ctx, `SELECT id FROM users WHERE clerk_id=$1`, subject).Scan(&canonical); err != nil {
			return Onboarding{}, err
		}
		if id != canonical {
			return Onboarding{}, Fault{"STATE_CONFLICT"}
		}
		return Onboarding{UserID: id, Status: "active", RefreshSession: true}, nil
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

func (s *Service) Profile(ctx context.Context, actor uuid.UUID) (Profile, error) {
	return s.Store.Profile(ctx, actor)
}

func (s *Service) UpdateProfile(ctx context.Context, actor uuid.UUID, name, avatar *string) (Profile, error) {
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
	completed, err := s.GetOnboarding(ctx, subject)
	if err != nil || completed.Status == "active" {
		return completed, err
	}
	id, err := s.Store.EnsureUser(ctx, subject)
	return Onboarding{UserID: id, Status: "pending"}, err
}
