package workspace

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"strings"
	"time"
	"unicode/utf8"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/qninhdt/openlet/packages/go/authz"
	shared "github.com/qninhdt/openlet/packages/go/temporal"
)

type Fault struct{ Code string }

func (e Fault) Error() string { return e.Code }
func (e Fault) Unwrap() error {
	kind := apperr.Conflict
	switch e.Code {
	case "VALIDATION":
		kind = apperr.Invalid
	case "FORBIDDEN", "INVITATION_EMAIL_MISMATCH":
		kind = apperr.Forbidden
	case "NOT_FOUND":
		kind = apperr.Missing
	case "REQUEST_LIMIT":
		kind = apperr.Limit
	}
	return apperr.New(kind, e.Code, strings.ToLower(strings.ReplaceAll(e.Code, "_", " ")))
}

type Store struct {
	Graph      v1.PermissionsServiceClient
	DB         *pgxpool.Pool
	MaxMembers int
	InviteTTL  time.Duration
}
type Workspace struct {
	ID              uuid.UUID `json:"id"`
	Name            string    `json:"name"`
	FilesystemID    uuid.UUID `json:"filesystem_id"`
	SharedScopeID   uuid.UUID `json:"shared_scope_id"`
	PersonalScopeID uuid.UUID `json:"personal_scope_id,omitempty"`
	Status          string    `json:"status"`
	Role            string    `json:"role,omitempty"`
}
type CreateInput = shared.WorkspaceCreation

type Creation struct {
	Input           CreateInput
	ID              uuid.UUID
	FilesystemID    uuid.UUID
	SharedScopeID   uuid.UUID
	PersonalScopeID uuid.UUID
}
type Member struct {
	AccountID       uuid.UUID `json:"account_id"`
	Role            string    `json:"role"`
	PersonalScopeID uuid.UUID `json:"personal_scope_id"`
	Status          string    `json:"status"`
}
type UpdateInput struct {
	Name *string `json:"name"`
}

func ValidateName(name string) error {
	if !utf8.ValidString(name) || utf8.RuneCountInString(name) > 100 || strings.TrimSpace(name) == "" || strings.ContainsRune(name, '\x00') {
		return Fault{"VALIDATION"}
	}
	return nil
}
func Fingerprint(value any) string {
	data, _ := json.Marshal(value)
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}
func (v Workspace) checkActive() error {
	if v.Status == "deleted" {
		return Fault{"NOT_FOUND"}
	}
	if v.Status != "active" {
		return Fault{"WORKSPACE_DELETING"}
	}
	return nil
}

const workspaceColumns = `w.id,w.name,w.filesystem_id,w.shared_scope_id,w.status,m.role,m.personal_scope_id`

func scanWorkspace(row pgx.Row) (Workspace, error) {
	var value Workspace
	err := row.Scan(&value.ID, &value.Name, &value.FilesystemID, &value.SharedScopeID, &value.Status, &value.Role, &value.PersonalScopeID)
	if errors.Is(err, pgx.ErrNoRows) {
		return value, Fault{"NOT_FOUND"}
	}
	return value, err
}
func (s *Store) getInTransaction(ctx context.Context, tx pgx.Tx, id, actor uuid.UUID) (Workspace, error) {
	return scanWorkspace(tx.QueryRow(ctx, `SELECT `+workspaceColumns+` FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE w.id=$1 AND m.account_id=$2 AND m.status='active'`, id, actor))
}
func (s *Store) Get(ctx context.Context, id, actor uuid.UUID) (Workspace, error) {
	return scanWorkspace(s.DB.QueryRow(ctx, `SELECT `+workspaceColumns+` FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE w.id=$1 AND m.account_id=$2 AND m.status='active'`, id, actor))
}
func (s *Store) FindCreation(ctx context.Context, in CreateInput) (Workspace, bool, error) {
	var id uuid.UUID
	var hash string
	err := s.DB.QueryRow(ctx, `SELECT workspace_id,request_hash FROM idempotency_keys WHERE actor_id=$1 AND request_key=$2 AND expires_at IS NOT NULL`, in.ActorID, in.Key).Scan(&id, &hash)
	if errors.Is(err, pgx.ErrNoRows) {
		return Workspace{}, false, nil
	}
	if err != nil {
		return Workspace{}, false, err
	}
	if hash != Fingerprint(in) {
		return Workspace{}, false, Fault{"IDEMPOTENCY_CONFLICT"}
	}
	value, err := s.Get(ctx, id, in.ActorID)
	return value, true, err
}
func (s *Store) SaveWorkspace(ctx context.Context, in Creation) (Workspace, error) {
	if err := ValidateName(in.Input.Name); err != nil {
		return Workspace{}, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return Workspace{}, err
	}
	defer tx.Rollback(ctx)
	// The receipt and mapping commit together; retries never compensate committed storage.
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, in.Input.ActorID.String()+in.Input.Key.String()); err != nil {
		return Workspace{}, err
	}
	var id uuid.UUID
	var hash string
	err = tx.QueryRow(ctx, `SELECT workspace_id,request_hash FROM idempotency_keys WHERE actor_id=$1 AND request_key=$2`, in.Input.ActorID, in.Input.Key).Scan(&id, &hash)
	if err == nil {
		if hash != Fingerprint(in.Input) || id != in.ID {
			return Workspace{}, Fault{"IDEMPOTENCY_CONFLICT"}
		}
		return s.getInTransaction(ctx, tx, id, in.Input.ActorID)
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return Workspace{}, err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO workspaces(id,name,filesystem_id,shared_scope_id) VALUES($1,$2,$3,$4)`, in.ID, in.Input.Name, in.FilesystemID, in.SharedScopeID); err != nil {
		return Workspace{}, err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO workspace_members(workspace_id,account_id,role,personal_scope_id) VALUES($1,$2,'owner',$3)`, in.ID, in.Input.ActorID, in.PersonalScopeID); err != nil {
		return Workspace{}, err
	}
	if err = saveMutationReceipt(ctx, tx, MutationReceipt{Key: in.Input.Key, Hash: Fingerprint(in.Input)}, in.Input.ActorID, in.ID); err != nil {
		return Workspace{}, err
	}
	value, err := s.getInTransaction(ctx, tx, in.ID, in.Input.ActorID)
	if err != nil {
		return value, err
	}
	return value, tx.Commit(ctx)
}
func (s *Store) List(ctx context.Context, actor, after uuid.UUID, limit int) ([]Workspace, error) {
	rows, err := s.DB.Query(ctx, `SELECT `+workspaceColumns+` FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.account_id=$1 AND m.status='active' AND w.status<>'deleted' AND w.id>$2 ORDER BY w.id LIMIT $3`, actor, after, limit)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (Workspace, error) { return scanWorkspace(row) })
}
func (s *Store) Members(ctx context.Context, id, after uuid.UUID, limit int) ([]Member, error) {
	rows, err := s.DB.Query(ctx, `SELECT account_id,role,personal_scope_id,status FROM workspace_members WHERE workspace_id=$1 AND account_id>$2 AND status='active' ORDER BY account_id LIMIT $3`, id, after, limit)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowToStructByPos[Member])
}
func (s *Store) Member(ctx context.Context, id, account uuid.UUID) (Member, error) {
	var value Member
	err := s.DB.QueryRow(ctx, `SELECT account_id,role,personal_scope_id,status FROM workspace_members WHERE workspace_id=$1 AND account_id=$2`, id, account).Scan(&value.AccountID, &value.Role, &value.PersonalScopeID, &value.Status)
	if errors.Is(err, pgx.ErrNoRows) {
		return value, Fault{"NOT_FOUND"}
	}
	return value, err
}
func (s *Store) Update(ctx context.Context, id, actor uuid.UUID, in UpdateInput) (Workspace, error) {
	if in.Name == nil {
		return Workspace{}, Fault{"VALIDATION"}
	}
	if err := ValidateName(*in.Name); err != nil {
		return Workspace{}, err
	}
	observed, err := s.Authorize(ctx, id, actor, authz.WorkspaceUpdate)
	if err != nil {
		return Workspace{}, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return Workspace{}, err
	}
	defer tx.Rollback(ctx)
	if _, err = s.lockAdmission(ctx, tx, observed, actor); err != nil {
		return Workspace{}, err
	}
	if _, err = tx.Exec(ctx, `UPDATE workspaces SET name=$2,updated_at=now() WHERE id=$1`, id, *in.Name); err != nil {
		return Workspace{}, err
	}
	value, err := s.getInTransaction(ctx, tx, id, actor)
	if err != nil {
		return value, err
	}
	return value, tx.Commit(ctx)
}
