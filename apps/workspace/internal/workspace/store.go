package workspace

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type Fault struct{ Code string }

func (e Fault) Error() string { return e.Code }

type Store struct {
	Graph                     v1.PermissionsServiceClient
	DB                        *pgxpool.Pool
	MaxWorkspaces, MaxMembers int
	QuotaLimit                int64
	InviteTTL                 time.Duration
}
type Workspace struct {
	ID           uuid.UUID  `json:"id"`
	Name         string     `json:"name"`
	Status       string     `json:"status"`
	ErrorCode    *string    `json:"error_code,omitempty"`
	BucketID     *uuid.UUID `json:"quota_bucket_id"`
	FilesystemID *uuid.UUID `json:"filesystem_id"`
	RootID       *uuid.UUID `json:"root_id"`
	LimitBytes   string     `json:"limit_bytes"`
	Revision     string     `json:"revision"`
	Role         string     `json:"role,omitempty"`
}
type Storage struct {
	LimitBytes   string    `json:"limit_bytes"`
	WorkspaceID  uuid.UUID `json:"workspace_id"`
	BucketID     uuid.UUID `json:"quota_bucket_id"`
	FilesystemID uuid.UUID `json:"filesystem_id"`
	RootID       uuid.UUID `json:"root_id"`
}
type CreateInput struct {
	ActorID uuid.UUID `json:"actor_id"`
	Key     uuid.UUID `json:"request_key"`
	Name    string    `json:"name"`
}

func ValidateName(name string) error {
	if !utf8.ValidString(name) || utf8.RuneCountInString(name) > 100 || strings.TrimSpace(name) == "" || strings.ContainsRune(name, '\x00') {
		return Fault{"VALIDATION"}
	}
	return nil
}
func Fingerprint(v any) string {
	b, _ := json.Marshal(v)
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}
func (s *Store) EnsureWorkspace(ctx context.Context, in CreateInput) (Workspace, error) {
	if in.ActorID == uuid.Nil || in.Key == uuid.Nil {
		return Workspace{}, Fault{"VALIDATION"}
	}
	if err := ValidateName(in.Name); err != nil {
		return Workspace{}, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return Workspace{}, err
	}
	defer tx.Rollback(ctx)
	// Serialize owner admission before enforcing the workspace limit.
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, in.ActorID.String()); err != nil {
		return Workspace{}, err
	}
	var id uuid.UUID
	var hash string
	err = tx.QueryRow(ctx, `SELECT workspace_id,request_hash FROM idempotency_keys WHERE actor_id=$1 AND request_key=$2 AND (expires_at IS NULL OR expires_at>now())`, in.ActorID, in.Key).Scan(&id, &hash)
	if err == nil {
		if hash != Fingerprint(in) {
			return Workspace{}, Fault{"IDEMPOTENCY_CONFLICT"}
		}
		value, err := s.getInTransaction(ctx, tx, id, in.ActorID)
		return value, err
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return Workspace{}, err
	}
	if _, err = tx.Exec(ctx, `DELETE FROM idempotency_keys WHERE actor_id=$1 AND request_key=$2 AND expires_at<=now()`, in.ActorID, in.Key); err != nil {
		return Workspace{}, err
	}
	var count int
	if err = tx.QueryRow(ctx, `SELECT count(*) FROM workspace_members m JOIN workspaces w ON w.id=m.workspace_id WHERE m.user_id=$1 AND m.role='owner' AND w.status!='deleted'`, in.ActorID).Scan(&count); err != nil {
		return Workspace{}, err
	}
	if count >= s.MaxWorkspaces {
		return Workspace{}, Fault{"RESOURCE_LIMIT"}
	}
	id = uuid.Must(uuid.NewV7())

	if _, err = tx.Exec(ctx, `INSERT INTO workspaces(id,name,limit_bytes) VALUES($1,$2,$3)`, id, in.Name, s.QuotaLimit); err != nil {
		return Workspace{}, err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO workspace_members(workspace_id,user_id,role) VALUES($1,$2,'owner')`, id, in.ActorID); err != nil {
		return Workspace{}, err
	}
	if _, err = tx.Exec(ctx, `INSERT INTO idempotency_keys(actor_id,request_key,request_hash,workspace_id) VALUES($1,$2,$3,$4)`, in.ActorID, in.Key, Fingerprint(in), id); err != nil {
		return Workspace{}, err
	}
	value, err := s.getInTransaction(ctx, tx, id, in.ActorID)
	if err != nil {
		return Workspace{}, err
	}
	return value, tx.Commit(ctx)
}
func (s *Store) getInTransaction(ctx context.Context, tx pgx.Tx, id, actor uuid.UUID) (Workspace, error) {
	var v Workspace
	err := tx.QueryRow(ctx, `SELECT w.id,w.name,w.status,w.revision::text,w.quota_bucket_id,w.filesystem_id,w.root_id,w.limit_bytes::text,m.role,w.error_code FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE w.id=$1 AND m.user_id=$2`, id, actor).Scan(&v.ID, &v.Name, &v.Status, &v.Revision, &v.BucketID, &v.FilesystemID, &v.RootID, &v.LimitBytes, &v.Role, &v.ErrorCode)
	if errors.Is(err, pgx.ErrNoRows) {
		return v, Fault{"NOT_FOUND"}
	}
	return v, err
}

// ReserveStorage persists caller-owned IDs before the Go storage workflow sends remote creates.
func (s *Store) ReserveStorage(ctx context.Context, id uuid.UUID) (Storage, error) {
	var result Storage
	if id == uuid.Nil {
		return result, Fault{"VALIDATION"}
	}
	err := s.DB.QueryRow(ctx, `UPDATE workspaces
		SET quota_bucket_id=COALESCE(quota_bucket_id,$2),filesystem_id=COALESCE(filesystem_id,$3)
		WHERE id=$1 AND status IN ('provisioning','active')
		RETURNING id,quota_bucket_id,filesystem_id,COALESCE(root_id,'00000000-0000-0000-0000-000000000000'::uuid),limit_bytes::text`,
		id, uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())).Scan(&result.WorkspaceID, &result.BucketID, &result.FilesystemID, &result.RootID, &result.LimitBytes)
	if errors.Is(err, pgx.ErrNoRows) {
		return result, Fault{"STATE_CONFLICT"}
	}
	return result, err
}

func (s *Store) Activate(ctx context.Context, mapping Storage) error {
	if mapping.WorkspaceID == uuid.Nil || mapping.BucketID == uuid.Nil || mapping.FilesystemID == uuid.Nil || mapping.RootID == uuid.Nil {
		return Fault{"VALIDATION"}
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	result, err := tx.Exec(ctx, `UPDATE workspaces SET status='active',quota_bucket_id=$2,filesystem_id=$3,root_id=$4,updated_at=now()
		WHERE id=$1 AND status IN ('provisioning','active')
		AND (quota_bucket_id IS NULL OR quota_bucket_id=$2) AND (filesystem_id IS NULL OR filesystem_id=$3)
		AND (root_id IS NULL OR root_id=$4)`, mapping.WorkspaceID, mapping.BucketID, mapping.FilesystemID, mapping.RootID)
	if err != nil {
		return err
	}
	if result.RowsAffected() != 1 {
		return Fault{"STATE_CONFLICT"}
	}
	return tx.Commit(ctx)
}
func (s *Store) Fail(ctx context.Context, id uuid.UUID) error {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, `UPDATE workspaces SET status='failed',error_code='WORKFLOW_FAILED',updated_at=now() WHERE id=$1 AND status='provisioning'`, id); err != nil {
		return err
	}
	if _, err = tx.Exec(ctx, `UPDATE idempotency_keys SET expires_at=COALESCE(expires_at,now()+interval '24 hours') WHERE workspace_id=$1 AND EXISTS(SELECT 1 FROM workspaces WHERE id=$1 AND status='failed')`, id); err != nil {
		return err
	}
	return tx.Commit(ctx)
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

func (s *Store) Get(ctx context.Context, ws, actor uuid.UUID) (Workspace, error) {
	var v Workspace
	var revision int64
	e := s.DB.QueryRow(ctx, `SELECT w.id,w.name,w.status,w.revision,m.role,w.quota_bucket_id,w.filesystem_id,w.root_id,w.limit_bytes::text,w.error_code FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE w.id=$1 AND m.user_id=$2`, ws, actor).Scan(&v.ID, &v.Name, &v.Status, &revision, &v.Role, &v.BucketID, &v.FilesystemID, &v.RootID, &v.LimitBytes, &v.ErrorCode)
	if errors.Is(e, pgx.ErrNoRows) {
		return v, Fault{"NOT_FOUND"}
	}
	if e != nil {
		return v, e
	}
	v.Revision = strconv.FormatInt(revision, 10)
	return v, nil
}

func (s *Store) List(ctx context.Context, actor, after uuid.UUID, limit int) ([]Workspace, error) {
	rows, e := s.DB.Query(ctx, `SELECT w.id,w.name,w.status,w.revision,m.role,w.quota_bucket_id,w.filesystem_id,w.root_id,w.limit_bytes::text,w.error_code FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=$1 AND w.status!='deleted' AND w.id>$2 ORDER BY w.id LIMIT $3`, actor, after, limit)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []Workspace{}
	for rows.Next() {
		var v Workspace
		var rev int64
		if e = rows.Scan(&v.ID, &v.Name, &v.Status, &rev, &v.Role, &v.BucketID, &v.FilesystemID, &v.RootID, &v.LimitBytes, &v.ErrorCode); e != nil {
			return nil, e
		}
		v.Revision = strconv.FormatInt(rev, 10)
		out = append(out, v)
	}
	return out, rows.Err()
}

type UpdateInput struct {
	Name    *string    `json:"name"`
	OwnerID *uuid.UUID `json:"owner_id"`
}

func (s *Store) Update(ctx context.Context, ws, actor uuid.UUID, revision string, in UpdateInput) (Workspace, error) {
	if in.Name == nil && in.OwnerID == nil {
		return Workspace{}, Fault{"VALIDATION"}
	}
	if in.Name != nil {
		if err := ValidateName(*in.Name); err != nil {
			return Workspace{}, err
		}
	}
	if in.OwnerID != nil && *in.OwnerID == uuid.Nil {
		return Workspace{}, Fault{"VALIDATION"}
	}
	var observed Workspace
	var err error
	if in.Name != nil {
		observed, err = s.Authorize(ctx, ws, actor, authz.WorkspaceUpdate)
		if err != nil {
			return observed, err
		}
	}
	if in.OwnerID != nil {
		transfer, err := s.Authorize(ctx, ws, actor, authz.WorkspaceTransfer)
		if err != nil {
			return transfer, err
		}
		if in.Name != nil && (transfer.Revision != observed.Revision || transfer.Status != observed.Status) {
			return transfer, Fault{"REVISION_MISMATCH"}
		}
		observed = transfer
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return Workspace{}, err
	}
	defer tx.Rollback(ctx)
	value, err := s.lockAdmission(ctx, tx, observed, actor)
	if err != nil {
		return value, err
	}
	if value.Revision != revision {
		return value, Fault{"REVISION_MISMATCH"}
	}
	if in.OwnerID != nil {
		target := *in.OwnerID
		var previousOwner uuid.UUID
		if err = tx.QueryRow(ctx, `SELECT user_id FROM workspace_members WHERE workspace_id=$1 AND role='owner'`, ws).Scan(&previousOwner); err != nil {
			return value, err
		}
		if target == actor || target == previousOwner {
			return value, Fault{"VALIDATION"}
		}
		if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, target.String()); err != nil {
			return value, err
		}
		var count int
		if err = tx.QueryRow(ctx, `SELECT count(*) FROM workspace_members m JOIN workspaces w ON w.id=m.workspace_id WHERE m.user_id=$1 AND m.role='owner' AND w.status!='deleted'`, target).Scan(&count); err != nil {
			return value, err
		}
		if count >= s.MaxWorkspaces {
			return value, Fault{"RESOURCE_LIMIT"}
		}
		var exists bool
		if err = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM workspace_members WHERE workspace_id=$1 AND user_id=$2)`, ws, target).Scan(&exists); err != nil {
			return value, err
		}
		if !exists {
			return value, Fault{"NOT_FOUND"}
		}
		if _, err = tx.Exec(ctx, `UPDATE workspace_members SET role='editor' WHERE workspace_id=$1 AND user_id=$2`, ws, previousOwner); err != nil {
			return value, err
		}
		if _, err = tx.Exec(ctx, `UPDATE workspace_members SET role='owner' WHERE workspace_id=$1 AND user_id=$2`, ws, target); err != nil {
			return value, err
		}
		if actor == previousOwner {
			value.Role = "editor"
		}
	}
	var next int64
	if err = tx.QueryRow(ctx, `UPDATE workspaces SET name=COALESCE($2,name),revision=revision+1,updated_at=now() WHERE id=$1 RETURNING name,revision`, ws, in.Name).Scan(&value.Name, &next); err != nil {
		return value, err
	}
	value.Revision = strconv.FormatInt(next, 10)
	return value, tx.Commit(ctx)
}

type Member struct {
	UserID uuid.UUID `json:"user_id"`
	Role   string    `json:"role"`
}

func (s *Store) Members(ctx context.Context, ws, after uuid.UUID, limit int) ([]Member, error) {
	rows, e := s.DB.Query(ctx, `SELECT user_id,role FROM workspace_members WHERE workspace_id=$1 AND user_id>$2 ORDER BY user_id LIMIT $3`, ws, after, limit)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []Member{}
	for rows.Next() {
		var v Member
		if e = rows.Scan(&v.UserID, &v.Role); e != nil {
			return nil, e
		}
		out = append(out, v)
	}
	return out, rows.Err()
}
func (s *Store) ChangeMember(ctx context.Context, ws, actor, target uuid.UUID, role string, remove bool, revision string) error {
	if !remove && role != "editor" && role != "viewer" {
		return Fault{"VALIDATION"}
	}
	action := authz.MemberManage
	if remove && actor == target {
		action = authz.MemberLeave
	}
	observed, e := s.Authorize(ctx, ws, actor, action)
	if e != nil {
		return e
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	v, e := s.lockAdmission(ctx, tx, observed, actor)
	if e != nil {
		return e
	}
	if v.Revision != revision {
		return Fault{"REVISION_MISMATCH"}
	}
	var old string
	if e = tx.QueryRow(ctx, `SELECT role FROM workspace_members WHERE workspace_id=$1 AND user_id=$2`, ws, target).Scan(&old); errors.Is(e, pgx.ErrNoRows) {
		return Fault{"NOT_FOUND"}
	} else if e != nil {
		return e
	}
	if old == "owner" {
		return Fault{"OWNER_TRANSFER_REQUIRED"}
	}
	if remove {
		_, e = tx.Exec(ctx, `DELETE FROM workspace_members WHERE workspace_id=$1 AND user_id=$2`, ws, target)
	} else {
		_, e = tx.Exec(ctx, `UPDATE workspace_members SET role=$3 WHERE workspace_id=$1 AND user_id=$2`, ws, target, role)
	}
	if e != nil {
		return e
	}
	if _, e = tx.Exec(ctx, `UPDATE workspaces SET revision=revision+1,updated_at=now() WHERE id=$1`, ws); e != nil {
		return e
	}
	return tx.Commit(ctx)
}

func (s *Store) CompleteCreation(ctx context.Context, id uuid.UUID) error {
	_, err := s.DB.Exec(ctx, `UPDATE idempotency_keys SET expires_at=COALESCE(expires_at,now()+interval '24 hours') WHERE workspace_id=$1 AND EXISTS(SELECT 1 FROM workspaces WHERE id=$1 AND status IN ('active','deleting','deleted'))`, id)
	return err
}
