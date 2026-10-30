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

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Fault struct{ Code string }

func (e Fault) Error() string { return e.Code }

type Store struct {
	DB                        *pgxpool.Pool
	MaxWorkspaces, MaxMembers int
	QuotaLimit                int64
	InviteTTL                 time.Duration
}
type Workspace struct {
	ID       uuid.UUID `json:"id"`
	Name     string    `json:"name"`
	State    string    `json:"state"`
	Revision string    `json:"revision"`
	Role     string    `json:"role,omitempty"`
}
type Storage struct {
	LimitBytes   string    `json:"limit_bytes"`
	WorkspaceID  uuid.UUID `json:"workspace_id"`
	BucketID     uuid.UUID `json:"quota_bucket_id"`
	FilesystemID uuid.UUID `json:"filesystem_id"`
	RootID       uuid.UUID `json:"root_id"`
}
type Operation struct {
	ID          uuid.UUID       `json:"operation_id"`
	WorkspaceID uuid.UUID       `json:"workspace_id"`
	ActorID     uuid.UUID       `json:"-"`
	Kind        string          `json:"kind"`
	Key         uuid.UUID       `json:"-"`
	Fingerprint string          `json:"-"`
	State       string          `json:"state"`
	Result      json.RawMessage `json:"result,omitempty"`
	ErrorCode   *string         `json:"error_code,omitempty"`
}
type CreateInput struct {
	ActorID     uuid.UUID `json:"actor_id"`
	Key         uuid.UUID `json:"request_key"`
	WorkspaceID uuid.UUID `json:"workspace_id"`
	Name        string    `json:"name"`
}
type Provision struct {
	Operation Operation
	Storage   Storage
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
func scanOperation(row pgx.Row) (Operation, error) {
	var v Operation
	e := row.Scan(&v.ID, &v.WorkspaceID, &v.ActorID, &v.Kind, &v.Key, &v.Fingerprint, &v.State, &v.Result, &v.ErrorCode)
	if errors.Is(e, pgx.ErrNoRows) {
		return v, Fault{"NOT_FOUND"}
	}
	return v, e
}

const opColumns = "id,workspace_id,actor_id,kind,request_key,fingerprint,state,result,error_code"

func (s *Store) OperationByKey(ctx context.Context, actor uuid.UUID, kind string, key uuid.UUID) (Operation, error) {
	return scanOperation(s.DB.QueryRow(ctx, `SELECT `+opColumns+` FROM operations WHERE actor_id=$1 AND kind=$2 AND request_key=$3`, actor, kind, key))
}
func (s *Store) Operation(ctx context.Context, id uuid.UUID) (Operation, error) {
	return scanOperation(s.DB.QueryRow(ctx, `SELECT `+opColumns+` FROM operations WHERE id=$1`, id))
}
func (s *Store) EnsureWorkspace(ctx context.Context, in CreateInput) (Provision, error) {
	if in.ActorID == uuid.Nil || in.Key == uuid.Nil {
		return Provision{}, Fault{"VALIDATION"}
	}
	if e := ValidateName(in.Name); e != nil {
		return Provision{}, e
	}
	fp := Fingerprint(in)
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return Provision{}, e
	}
	defer tx.Rollback(ctx)
	// Serialize owner admission before counting concurrent workspace creations.
	if _, e = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, in.ActorID.String()); e != nil {
		return Provision{}, e
	}
	existing, e := scanOperation(tx.QueryRow(ctx, `SELECT `+opColumns+` FROM operations WHERE actor_id=$1 AND kind='create' AND request_key=$2`, in.ActorID, in.Key))
	if e == nil {
		if existing.Fingerprint != fp {
			return Provision{}, Fault{"IDEMPOTENCY_CONFLICT"}
		}
		var v Storage
		v.WorkspaceID = existing.WorkspaceID
		e = tx.QueryRow(ctx, `SELECT quota_bucket_id,filesystem_id,root_id,limit_bytes::text FROM workspace_storage WHERE workspace_id=$1`, existing.WorkspaceID).Scan(&v.BucketID, &v.FilesystemID, &v.RootID, &v.LimitBytes)
		return Provision{Operation: existing, Storage: v}, e
	}
	var f Fault
	if !errors.As(e, &f) || f.Code != "NOT_FOUND" {
		return Provision{}, e
	}
	var count int
	if e = tx.QueryRow(ctx, `SELECT count(*) FROM workspace_members m JOIN workspaces w ON w.id=m.workspace_id WHERE m.user_id=$1 AND m.role='owner' AND w.state!='deleted'`, in.ActorID).Scan(&count); e != nil {
		return Provision{}, e
	}
	if count >= s.MaxWorkspaces {
		return Provision{}, Fault{"RESOURCE_LIMIT"}
	}
	id := in.WorkspaceID
	if id == uuid.Nil {
		id = uuid.Must(uuid.NewV7())
	}
	op := Operation{ID: uuid.Must(uuid.NewV7()), WorkspaceID: id, ActorID: in.ActorID, Kind: "create", Key: in.Key, Fingerprint: fp, State: "running"}
	storage := Storage{LimitBytes: strconv.FormatInt(s.QuotaLimit, 10), WorkspaceID: id, BucketID: uuid.Must(uuid.NewV7()), FilesystemID: uuid.Must(uuid.NewV7()), RootID: uuid.Must(uuid.NewV7())}
	_, e = tx.Exec(ctx, `INSERT INTO workspaces(id,name,provision_key) VALUES($1,$2,$3)`, id, in.Name, "workspace/"+in.ActorID.String()+"/"+in.Key.String())
	if e != nil {
		return Provision{}, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO workspace_members(workspace_id,user_id,role) VALUES($1,$2,'owner')`, id, in.ActorID)
	if e != nil {
		return Provision{}, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO workspace_storage(workspace_id,quota_bucket_id,filesystem_id,root_id,limit_bytes) VALUES($1,$2,$3,$4,$5)`, id, storage.BucketID, storage.FilesystemID, storage.RootID, s.QuotaLimit)
	if e != nil {
		return Provision{}, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO operations(id,workspace_id,actor_id,kind,request_key,fingerprint) VALUES($1,$2,$3,'create',$4,$5)`, op.ID, id, in.ActorID, in.Key, fp)
	if e != nil {
		return Provision{}, e
	}
	if e = tx.Commit(ctx); e != nil {
		return Provision{}, e
	}
	return Provision{Operation: op, Storage: storage}, nil
}
func (s *Store) Activate(ctx context.Context, opID uuid.UUID) error {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	var wsID uuid.UUID
	if e = tx.QueryRow(ctx, `SELECT workspace_id FROM operations WHERE id=$1`, opID).Scan(&wsID); e != nil {
		return e
	}
	var wsState string
	if e = tx.QueryRow(ctx, `SELECT state FROM workspaces WHERE id=$1 FOR UPDATE`, wsID).Scan(&wsState); e != nil {
		return e
	}
	var state string
	if e = tx.QueryRow(ctx, `SELECT state FROM operations WHERE id=$1 FOR UPDATE`, opID).Scan(&state); e != nil {
		return e
	}
	if state == "succeeded" {
		return nil
	}
	if state != "running" {
		return Fault{"STATE_CONFLICT"}
	}
	if wsState != "provisioning" {
		return Fault{"STATE_CONFLICT"}
	}
	_, e = tx.Exec(ctx, `UPDATE workspaces SET state='active',updated_at=now() WHERE id=$1`, wsID)
	if e != nil {
		return e
	}
	result, _ := json.Marshal(map[string]uuid.UUID{"workspace_id": wsID})
	_, e = tx.Exec(ctx, `UPDATE operations SET state='succeeded',result=$2,updated_at=now() WHERE id=$1`, opID, result)
	if e != nil {
		return e
	}
	return tx.Commit(ctx)
}
func (s *Store) Fail(ctx context.Context, id uuid.UUID) error {
	_, e := s.DB.Exec(ctx, `UPDATE operations SET state='failed',error_code='WORKFLOW_FAILED',updated_at=now() WHERE id=$1 AND state='running'`, id)
	return e
}

func authorize(ctx context.Context, tx pgx.Tx, ws, actor uuid.UUID, minimum string) (Workspace, error) {
	var v Workspace
	var revision int64
	e := tx.QueryRow(ctx, `SELECT id,name,state,revision FROM workspaces WHERE id=$1 FOR UPDATE`, ws).Scan(&v.ID, &v.Name, &v.State, &revision)
	if errors.Is(e, pgx.ErrNoRows) {
		return v, Fault{"NOT_FOUND"}
	}
	if e != nil {
		return v, e
	}
	// Read current membership only after acquiring the workspace lock.
	e = tx.QueryRow(ctx, `SELECT role FROM workspace_members WHERE workspace_id=$1 AND user_id=$2`, ws, actor).Scan(&v.Role)
	if errors.Is(e, pgx.ErrNoRows) {
		return v, Fault{"NOT_FOUND"}
	}
	if e != nil {
		return v, e
	}
	v.Revision = strconv.FormatInt(revision, 10)
	return v, v.checkAccess(minimum)
}

func (v Workspace) checkAccess(minimum string) error {
	if v.State != "active" {
		return Fault{"WORKSPACE_DELETING"}
	}
	if (minimum == "owner" && v.Role != "owner") || (minimum == "editor" && v.Role == "viewer") {
		return Fault{"FORBIDDEN"}
	}
	return nil
}

func (s *Store) Authorize(ctx context.Context, ws, actor uuid.UUID, minimum string) (Workspace, error) {
	var v Workspace
	var revision int64
	e := s.DB.QueryRow(ctx, `SELECT w.id,w.name,w.state,w.revision,m.role FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE w.id=$1 AND m.user_id=$2`, ws, actor).Scan(&v.ID, &v.Name, &v.State, &revision, &v.Role)
	if errors.Is(e, pgx.ErrNoRows) {
		return v, Fault{"NOT_FOUND"}
	}
	if e != nil {
		return v, e
	}
	v.Revision = strconv.FormatInt(revision, 10)
	return v, v.checkAccess(minimum)
}
func (s *Store) Storage(ctx context.Context, ws uuid.UUID) (Storage, error) {
	var v Storage
	v.WorkspaceID = ws
	e := s.DB.QueryRow(ctx, `SELECT quota_bucket_id,filesystem_id,root_id,limit_bytes::text FROM workspace_storage WHERE workspace_id=$1`, ws).Scan(&v.BucketID, &v.FilesystemID, &v.RootID, &v.LimitBytes)
	return v, e
}
func (s *Store) List(ctx context.Context, actor, after uuid.UUID, limit int) ([]Workspace, error) {
	rows, e := s.DB.Query(ctx, `SELECT w.id,w.name,w.state,w.revision,m.role FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=$1 AND w.state='active' AND w.id>$2 ORDER BY w.id LIMIT $3`, actor, after, limit)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []Workspace{}
	for rows.Next() {
		var v Workspace
		var rev int64
		if e = rows.Scan(&v.ID, &v.Name, &v.State, &rev, &v.Role); e != nil {
			return nil, e
		}
		v.Revision = strconv.FormatInt(rev, 10)
		out = append(out, v)
	}
	return out, rows.Err()
}
func (s *Store) Rename(ctx context.Context, ws, actor uuid.UUID, name, revision string) (Workspace, error) {
	if e := ValidateName(name); e != nil {
		return Workspace{}, e
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return Workspace{}, e
	}
	defer tx.Rollback(ctx)
	v, e := authorize(ctx, tx, ws, actor, "owner")
	if e != nil {
		return v, e
	}
	if v.Revision != revision {
		return v, Fault{"REVISION_MISMATCH"}
	}
	var rev int64
	e = tx.QueryRow(ctx, `UPDATE workspaces SET name=$2,revision=revision+1,updated_at=now() WHERE id=$1 RETURNING revision`, ws, name).Scan(&rev)
	if e != nil {
		return v, e
	}
	v.Name = name
	v.Revision = strconv.FormatInt(rev, 10)
	return v, tx.Commit(ctx)
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
func (s *Store) ChangeMember(ctx context.Context, ws, actor, target uuid.UUID, role string, remove bool) error {
	if !remove && role != "editor" && role != "viewer" {
		return Fault{"VALIDATION"}
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	v, e := authorize(ctx, tx, ws, actor, "viewer")
	if e != nil {
		return e
	}
	if v.Role != "owner" && (!remove || actor != target) {
		return Fault{"FORBIDDEN"}
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
	return tx.Commit(ctx)
}
func (s *Store) Transfer(ctx context.Context, ws, actor, target uuid.UUID) error {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	if _, e = authorize(ctx, tx, ws, actor, "owner"); e != nil {
		return e
	}
	if actor == target {
		return Fault{"VALIDATION"}
	}
	// Serialize ownership admission with workspace creation for this recipient.
	if _, e = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtextextended($1,0))`, target.String()); e != nil {
		return e
	}
	var owned int
	if e = tx.QueryRow(ctx, `SELECT count(*) FROM workspace_members m JOIN workspaces w ON w.id=m.workspace_id WHERE m.user_id=$1 AND m.role='owner' AND w.state!='deleted'`, target).Scan(&owned); e != nil {
		return e
	}
	if owned >= s.MaxWorkspaces {
		return Fault{"RESOURCE_LIMIT"}
	}
	var role string
	if e = tx.QueryRow(ctx, `SELECT role FROM workspace_members WHERE workspace_id=$1 AND user_id=$2`, ws, target).Scan(&role); errors.Is(e, pgx.ErrNoRows) {
		return Fault{"NOT_FOUND"}
	} else if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE workspace_members SET role='editor' WHERE workspace_id=$1 AND user_id=$2`, ws, actor)
	if e != nil {
		return e
	}
	_, e = tx.Exec(ctx, `UPDATE workspace_members SET role='owner' WHERE workspace_id=$1 AND user_id=$2`, ws, target)
	if e != nil {
		return e
	}
	return tx.Commit(ctx)
}
