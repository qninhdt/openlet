package user

import (
	"context"
	"errors"
	"net/url"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Fault struct{ Code string }

func (e Fault) Error() string { return e.Code }

type Store struct{ DB *pgxpool.Pool }
type Profile struct {
	ID          uuid.UUID `json:"id"`
	DisplayName string    `json:"display_name"`
	AvatarURL   string    `json:"avatar_url"`
}
type Onboarding struct {
	OperationID    uuid.UUID `json:"operation_id"`
	UserID         uuid.UUID `json:"user_id"`
	WorkspaceID    uuid.UUID `json:"workspace_id"`
	WorkspaceKey   uuid.UUID `json:"workspace_key"`
	State          string    `json:"state"`
	RefreshSession bool      `json:"refresh_session"`
}

func (s *Store) Onboarding(ctx context.Context, subject string) (Onboarding, error) {
	var v Onboarding
	e := s.DB.QueryRow(ctx, `SELECT o.id,u.id,u.initial_workspace_id,u.initial_workspace_key,o.state FROM users u JOIN operations o ON o.subject=u.clerk_id WHERE u.clerk_id=$1`, subject).Scan(&v.OperationID, &v.UserID, &v.WorkspaceID, &v.WorkspaceKey, &v.State)
	if errors.Is(e, pgx.ErrNoRows) {
		return v, Fault{"NOT_FOUND"}
	}
	v.RefreshSession = v.State == "succeeded"
	return v, e
}
func (s *Store) EnsureUser(ctx context.Context, subject string) (Onboarding, error) {
	if subject == "" || len(subject) > 200 || strings.ContainsAny(subject, "\r\n\x00") {
		return Onboarding{}, Fault{"VALIDATION"}
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return Onboarding{}, e
	}
	defer tx.Rollback(ctx)
	_, e = tx.Exec(ctx, `INSERT INTO users(id,clerk_id,initial_workspace_id,initial_workspace_key) VALUES($1,$2,$3,$4) ON CONFLICT(clerk_id) DO NOTHING`, uuid.Must(uuid.NewV7()), subject, uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()))
	if e != nil {
		return Onboarding{}, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO operations(id,subject) VALUES($1,$2) ON CONFLICT(subject) DO NOTHING`, uuid.Must(uuid.NewV7()), subject)
	if e != nil {
		return Onboarding{}, e
	}
	if e = tx.Commit(ctx); e != nil {
		return Onboarding{}, e
	}
	return s.Onboarding(ctx, subject)
}
func (s *Store) Complete(ctx context.Context, subject string) error {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	var id uuid.UUID
	if e = tx.QueryRow(ctx, `SELECT id FROM users WHERE clerk_id=$1 FOR UPDATE`, subject).Scan(&id); e != nil {
		return e
	}
	var state string
	if e = tx.QueryRow(ctx, `SELECT state FROM operations WHERE subject=$1 FOR UPDATE`, subject).Scan(&state); e != nil {
		return e
	}
	if state == "succeeded" {
		return nil
	}
	if state != "running" {
		return Fault{"STATE_CONFLICT"}
	}
	_, e = tx.Exec(ctx, `UPDATE users SET onboarding_state='active',updated_at=now() WHERE clerk_id=$1`, subject)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE operations SET state='succeeded',updated_at=now() WHERE subject=$1`, subject)
	if e != nil {
		return e
	}
	return tx.Commit(ctx)
}
func (s *Store) Fail(ctx context.Context, subject string) error {
	_, e := s.DB.Exec(ctx, `UPDATE operations SET state='failed',updated_at=now() WHERE subject=$1 AND state='running'`, subject)
	return e
}
func (s *Store) Profile(ctx context.Context, id uuid.UUID) (Profile, error) {
	var p Profile
	e := s.DB.QueryRow(ctx, `SELECT id,display_name,avatar_url FROM users WHERE id=$1 AND onboarding_state='active'`, id).Scan(&p.ID, &p.DisplayName, &p.AvatarURL)
	if errors.Is(e, pgx.ErrNoRows) {
		return p, Fault{"NOT_FOUND"}
	}
	return p, e
}
func (s *Store) UpdateProfile(ctx context.Context, id uuid.UUID, name, avatar *string) (Profile, error) {
	if name != nil && (!utf8.ValidString(*name) || strings.ContainsRune(*name, '\x00') || utf8.RuneCountInString(*name) > 100) {
		return Profile{}, Fault{"VALIDATION"}
	}
	if avatar != nil {
		u, e := url.Parse(*avatar)
		if len(*avatar) > 2048 || (*avatar != "" && (e != nil || u.Scheme != "https" || u.Host == "" || u.User != nil)) {
			return Profile{}, Fault{"VALIDATION"}
		}
	}
	var p Profile
	e := s.DB.QueryRow(ctx, `UPDATE users SET display_name=COALESCE($2,display_name),avatar_url=COALESCE($3,avatar_url),updated_at=now() WHERE id=$1 AND onboarding_state='active' RETURNING id,display_name,avatar_url`, id, name, avatar).Scan(&p.ID, &p.DisplayName, &p.AvatarURL)
	if errors.Is(e, pgx.ErrNoRows) {
		return p, Fault{"NOT_FOUND"}
	}
	return p, e
}

func (s *Store) Summaries(ctx context.Context, ids []uuid.UUID) ([]Profile, error) {
	if len(ids) == 0 || len(ids) > 100 {
		return nil, Fault{"VALIDATION"}
	}
	rows, e := s.DB.Query(ctx, `SELECT id,display_name,avatar_url FROM users WHERE id=ANY($1) AND onboarding_state='active' ORDER BY id`, ids)
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
	e := s.DB.QueryRow(ctx, `SELECT clerk_id FROM users WHERE id=$1 AND onboarding_state='active'`, id).Scan(&subject)
	if errors.Is(e, pgx.ErrNoRows) {
		return "", Fault{"NOT_FOUND"}
	}
	return subject, e
}
