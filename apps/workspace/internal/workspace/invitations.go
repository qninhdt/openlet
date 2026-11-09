package workspace

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"net/mail"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type Invitation struct {
	ID          uuid.UUID `json:"id"`
	WorkspaceID uuid.UUID `json:"workspace_id"`
	Email       string    `json:"email"`
	Role        string    `json:"role"`
	Status      string    `json:"status"`
	ExpiresAt   time.Time `json:"expires_at"`
}

func NormalizeEmail(value string) (string, error) {
	value = strings.ToLower(strings.TrimSpace(value))
	address, e := mail.ParseAddress(value)
	if e != nil || address.Address != value || len(value) > 254 || strings.ContainsAny(value, "\r\n") {
		return "", Fault{"VALIDATION"}
	}
	return value, nil
}
func (s *Store) Invite(ctx context.Context, ws, actor uuid.UUID, email, role string) (Invitation, string, error) {
	var v Invitation
	if role != "admin" && role != "member" {
		return v, "", Fault{"VALIDATION"}
	}
	email, e := NormalizeEmail(email)
	if e != nil {
		return v, "", e
	}
	observed, e := s.Authorize(ctx, ws, actor, authz.WorkspaceManageMembers)
	if e != nil {
		return v, "", e
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return v, "", e
	}
	defer tx.Rollback(ctx)
	if _, e = s.lockAdmission(ctx, tx, observed, actor); e != nil {
		return v, "", e
	}

	if _, e = tx.Exec(ctx, `UPDATE workspace_invitations SET status='expired' WHERE workspace_id=$1 AND email=$2 AND status='pending' AND expires_at<=now()`, ws, email); e != nil {
		return v, "", e
	}
	e = tx.QueryRow(ctx, `SELECT id,workspace_id,email,role,status,expires_at FROM workspace_invitations WHERE workspace_id=$1 AND email=$2 AND status='pending'`, ws, email).Scan(&v.ID, &v.WorkspaceID, &v.Email, &v.Role, &v.Status, &v.ExpiresAt)
	if e == nil {
		if v.Role != role {
			return Invitation{}, "", Fault{"INVITATION_CONFLICT"}
		}
		return v, "", tx.Commit(ctx)
	}
	if !errors.Is(e, pgx.ErrNoRows) {
		return Invitation{}, "", e
	}
	secret := make([]byte, 32)
	if _, e = rand.Read(secret); e != nil {
		return v, "", e
	}
	token := base64.RawURLEncoding.EncodeToString(secret)
	hash := sha256.Sum256([]byte(token))
	v = Invitation{ID: uuid.Must(uuid.NewV7()), WorkspaceID: ws, Email: email, Role: role, Status: "pending", ExpiresAt: time.Now().UTC().Add(s.InviteTTL)}
	_, e = tx.Exec(ctx, `INSERT INTO workspace_invitations(id,workspace_id,email,role,token_hash,expires_at) VALUES($1,$2,$3,$4,$5,$6)`, v.ID, ws, email, role, hash[:], v.ExpiresAt)
	if e != nil {
		return Invitation{}, "", e
	}
	if e = tx.Commit(ctx); e != nil {
		return Invitation{}, "", e
	}
	return v, token, nil
}
func (s *Store) Invitations(ctx context.Context, ws, after uuid.UUID, limit int) ([]Invitation, error) {
	rows, e := s.DB.Query(ctx, `SELECT id,workspace_id,email,role,status,expires_at FROM workspace_invitations WHERE workspace_id=$1 AND id>$2 ORDER BY id LIMIT $3`, ws, after, limit)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []Invitation{}
	for rows.Next() {
		var v Invitation
		if e = rows.Scan(&v.ID, &v.WorkspaceID, &v.Email, &v.Role, &v.Status, &v.ExpiresAt); e != nil {
			return nil, e
		}
		out = append(out, v)
	}
	return out, rows.Err()
}
func (s *Store) RevokeInvite(ctx context.Context, ws, actor, id uuid.UUID) error {
	observed, e := s.Authorize(ctx, ws, actor, authz.WorkspaceManageMembers)
	if e != nil {
		return e
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	if _, e = s.lockAdmission(ctx, tx, observed, actor); e != nil {
		return e
	}
	result, e := tx.Exec(ctx, `UPDATE workspace_invitations SET status='revoked' WHERE id=$1 AND workspace_id=$2 AND status='pending'`, id, ws)
	if e != nil {
		return e
	}
	if result.RowsAffected() == 0 {
		return Fault{"INVITATION_NOT_PENDING"}
	}
	return tx.Commit(ctx)
}

// AdmitInvitation verifies the token and trusted email before workflow admission.
func (s *Store) AdmitInvitation(ctx context.Context, actor uuid.UUID, hash [32]byte, emails []string) (uuid.UUID, string, error) {
	var ws uuid.UUID
	var email, role, status string
	var expires time.Time
	var accepted *uuid.UUID
	err := s.DB.QueryRow(ctx, `SELECT workspace_id,email,role,status,expires_at,accepted_user_id FROM workspace_invitations WHERE token_hash=$1`, hash[:]).Scan(&ws, &email, &role, &status, &expires, &accepted)
	if errors.Is(err, pgx.ErrNoRows) {
		return ws, "", Fault{"INVITATION_INVALID"}
	}
	if err != nil {
		return ws, "", err
	}
	matched := false
	for _, candidate := range emails {
		normalized, err := NormalizeEmail(candidate)
		if err == nil && normalized == email {
			matched = true
			break
		}
	}
	if !matched {
		return ws, "", Fault{"INVITATION_EMAIL_MISMATCH"}
	}
	if status == "accepted" {
		member, err := s.Member(ctx, ws, actor)
		if accepted == nil || *accepted != actor || err != nil || member.Status != "active" {
			return ws, "", Fault{"INVITATION_ALREADY_USED"}
		}
		return ws, member.Role, nil
	}
	if status != "pending" || !time.Now().Before(expires) {
		return ws, "", Fault{"INVITATION_INVALID"}
	}
	return ws, role, nil
}
