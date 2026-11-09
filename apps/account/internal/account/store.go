package account

import (
	"context"
	"errors"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"net/url"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Fault struct{ Code string }

func (e Fault) Error() string { return e.Code }
func (e Fault) Unwrap() error {
	kind := apperr.Invalid
	if e.Code == "NOT_FOUND" {
		kind = apperr.Missing
	}
	if e.Code == "FORBIDDEN" {
		kind = apperr.Forbidden
	}
	return apperr.New(kind, e.Code, strings.ToLower(strings.ReplaceAll(e.Code, "_", " ")))
}

type Store struct{ DB *pgxpool.Pool }
type Profile struct {
	ID          uuid.UUID `json:"id"`
	DisplayName string    `json:"display_name"`
	AvatarURL   string    `json:"avatar_url"`
}
type Onboarding struct {
	UserID         uuid.UUID `json:"user_id"`
	Status         string    `json:"status"`
	RefreshSession bool      `json:"refresh_session"`
}

func (s *Store) EnsureUser(ctx context.Context, subject string) (uuid.UUID, error) {
	if subject == "" || len(subject) > 200 || strings.ContainsAny(subject, "\r\n\x00") {
		return uuid.Nil, Fault{"VALIDATION"}
	}
	var id uuid.UUID
	err := s.DB.QueryRow(ctx, `INSERT INTO users(id,clerk_id) VALUES($1,$2)
      ON CONFLICT(clerk_id) DO UPDATE SET clerk_id=excluded.clerk_id RETURNING id`, uuid.Must(uuid.NewV7()), subject).Scan(&id)
	return id, err
}

func (s *Store) Profile(ctx context.Context, id uuid.UUID) (Profile, error) {
	var p Profile
	e := s.DB.QueryRow(ctx, `SELECT id,display_name,avatar_url FROM users WHERE id=$1`, id).Scan(&p.ID, &p.DisplayName, &p.AvatarURL)
	if errors.Is(e, pgx.ErrNoRows) {
		return p, Fault{"NOT_FOUND"}
	}
	return p, e
}
func (s *Store) UpdateProfile(ctx context.Context, id uuid.UUID, name, avatar *string) (Profile, error) {
	if err := validateProfile(name, avatar); err != nil {
		return Profile{}, err
	}
	var p Profile
	e := s.DB.QueryRow(ctx, `UPDATE users SET display_name=COALESCE($2,display_name),avatar_url=COALESCE($3,avatar_url),updated_at=now() WHERE id=$1 RETURNING id,display_name,avatar_url`, id, name, avatar).Scan(&p.ID, &p.DisplayName, &p.AvatarURL)
	if errors.Is(e, pgx.ErrNoRows) {
		return p, Fault{"NOT_FOUND"}
	}
	return p, e
}

func (s *Store) Summaries(ctx context.Context, ids []uuid.UUID) ([]Profile, error) {
	if len(ids) == 0 || len(ids) > 100 {
		return nil, Fault{"VALIDATION"}
	}
	rows, e := s.DB.Query(ctx, `SELECT id,display_name,avatar_url FROM users WHERE id=ANY($1) ORDER BY id`, ids)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	items := make([]Profile, 0, len(ids))
	for rows.Next() {
		var p Profile
		if e = rows.Scan(&p.ID, &p.DisplayName, &p.AvatarURL); e != nil {
			return nil, e
		}
		items = append(items, p)
	}
	return items, rows.Err()
}
func (s *Store) Subject(ctx context.Context, id uuid.UUID) (string, error) {
	var subject string
	e := s.DB.QueryRow(ctx, `SELECT clerk_id FROM users WHERE id=$1`, id).Scan(&subject)
	if errors.Is(e, pgx.ErrNoRows) {
		return "", Fault{"NOT_FOUND"}
	}
	if e != nil {
		return "", e
	}
	return subject, nil
}

func validateProfile(name, avatar *string) error {
	if name != nil && (!utf8.ValidString(*name) || strings.ContainsRune(*name, '\x00') || utf8.RuneCountInString(*name) > 100) {
		return Fault{"VALIDATION"}
	}
	if avatar != nil {
		u, e := url.Parse(*avatar)
		if len(*avatar) > 2048 || (*avatar != "" && (e != nil || u.Scheme != "https" || u.Host == "" || u.User != nil)) {
			return Fault{"VALIDATION"}
		}
	}
	return nil
}
