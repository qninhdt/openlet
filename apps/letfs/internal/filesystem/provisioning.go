package filesystem

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"
	"time"
	"unicode/utf8"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/search"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/identity"
	"golang.org/x/sync/semaphore"
)

type Store struct {
	DB                                             *pgxpool.Pool
	Graph                                          v1.PermissionsServiceClient
	MaxNodes, MaxCopyNodes                         int64
	InlineLimit, MaxFileBytes                      int64
	Storage                                        *storage.Client
	DownloadLifetime                               time.Duration
	MaxOutstanding, MaxCleanupBacklog              int64
	MultipartThreshold, MultipartPartBytes         int64
	UploadLifetime, UploadTransferGrace            time.Duration
	ProcessingMaxOutputs, ProcessingMaxOutputBytes int64
	IndexSpace                                     VectorSpace
	Search                                         *search.Client
	AI                                             *search.AI
	Archive                                        ArchiveConfig
	ArchiveSlots                                   *semaphore.Weighted
}

type Filesystem struct {
	ID         uuid.UUID `json:"id"`
	LimitBytes int64     `json:"limit_bytes,string"`
	UsedBytes  int64     `json:"used_bytes,string"`
	NodeCount  int64     `json:"node_count,string"`
	State      string    `json:"state"`
}

type CreateFilesystem struct {
	ID         uuid.UUID `json:"id"`
	LimitBytes int64     `json:"limit_bytes"`
}

type Scope struct {
	ID             uuid.UUID  `json:"id"`
	FilesystemID   uuid.UUID  `json:"filesystem_id"`
	RootID         *uuid.UUID `json:"root_id"`
	State          string     `json:"state"`
	AllowBlobFiles bool       `json:"allow_blob_files"`
	AllowIndexing  bool       `json:"allow_indexing"`
}

func service(ctx context.Context) (string, error) {
	principal, ok := identity.FromContext(ctx)
	if !ok || principal.Gateway || principal.Service == "" {
		return "", apperr.New(apperr.Forbidden, "FORBIDDEN", "service authority required")
	}
	return principal.Service, nil
}

func requestIdentity(id, key uuid.UUID) error {
	if id == uuid.Nil || id.Version() != 7 || key == uuid.Nil {
		return apperr.New(apperr.Invalid, "VALIDATION", "stable UUIDv7 identity and request key required")
	}
	return nil
}

func ValidateName(name string) error {
	if !utf8.ValidString(name) || len(name) == 0 || len(name) > 255 || name == "." || name == ".." || strings.ContainsAny(name, "/\x00") {
		return apperr.New(apperr.Invalid, "VALIDATION", "invalid name")
	}
	return nil
}

func fingerprint(input any) (string, error) {
	data, err := json.Marshal(input)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:]), nil
}

// The existing receipt checks request reuse; resource identity handles repeated creation.
func receipt(ctx context.Context, tx pgx.Tx, caller, operation string, key uuid.UUID, hash string, result any) error {
	data, err := json.Marshal(result)
	if err != nil {
		return err
	}
	var saved []byte
	err = tx.QueryRow(ctx, `INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result)
		VALUES($1,$2,$3,$4,$5) ON CONFLICT(scope,operation,request_key) DO UPDATE
		SET request_hash=excluded.request_hash WHERE idempotency_keys.request_hash=excluded.request_hash RETURNING result`,
		"service:"+caller, operation, key.String(), hash, data).Scan(&saved)
	if errors.Is(err, pgx.ErrNoRows) {
		return apperr.New(apperr.Conflict, "IDEMPOTENCY_CONFLICT", "request key was used for different input")
	}
	if err != nil {
		return err
	}
	return json.Unmarshal(saved, result)
}

func filesystemForUpdate(ctx context.Context, tx pgx.Tx, id uuid.UUID) (Filesystem, error) {
	var value Filesystem
	err := tx.QueryRow(ctx, `SELECT id,limit_bytes,used_bytes,node_count,state FROM filesystems WHERE id=$1 FOR UPDATE`, id).Scan(&value.ID, &value.LimitBytes, &value.UsedBytes, &value.NodeCount, &value.State)
	return value, databaseError(err)
}

func (s *Store) CreateFilesystem(ctx context.Context, key uuid.UUID, input CreateFilesystem) (Filesystem, error) {
	caller, err := service(ctx)
	if err != nil {
		return Filesystem{}, err
	}
	if err = requestIdentity(input.ID, key); err != nil {
		return Filesystem{}, err
	}
	if input.LimitBytes < 0 {
		return Filesystem{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid byte limit")
	}
	hash, err := fingerprint(input)
	if err != nil {
		return Filesystem{}, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return Filesystem{}, databaseError(err)
	}
	defer tx.Rollback(ctx)
	if _, err = tx.Exec(ctx, `INSERT INTO filesystems(id,limit_bytes) VALUES($1,$2) ON CONFLICT(id) DO NOTHING`, input.ID, input.LimitBytes); err != nil {
		return Filesystem{}, databaseError(err)
	}
	value, err := filesystemForUpdate(ctx, tx, input.ID)
	if err != nil {
		return Filesystem{}, err
	}
	if value.State != "active" || value.LimitBytes != input.LimitBytes {
		return Filesystem{}, apperr.New(apperr.Precondition, "SCOPE_CONFLICT", "filesystem input conflicts")
	}
	if err = receipt(ctx, tx, caller, "create-filesystem", key, hash, &value); err != nil {
		return Filesystem{}, err
	}
	return value, databaseError(tx.Commit(ctx))
}

func (s *Store) CreateScopes(ctx context.Context, key, fs uuid.UUID, ids []uuid.UUID, allowBlobFiles, allowIndexing bool) ([]Scope, error) {
	caller, err := service(ctx)
	if err != nil {
		return nil, err
	}
	if fs == uuid.Nil || key == uuid.Nil || len(ids) == 0 || len(ids) > 100 {
		return nil, apperr.New(apperr.Invalid, "VALIDATION", "invalid scope creation")
	}
	seen := map[uuid.UUID]bool{}
	for _, id := range ids {
		if err = requestIdentity(id, key); err != nil {
			return nil, err
		}
		if seen[id] {
			return nil, apperr.New(apperr.Invalid, "VALIDATION", "duplicate scope")
		}
		seen[id] = true
	}
	hash, err := fingerprint(struct {
		FilesystemID   uuid.UUID
		IDs            []uuid.UUID
		AllowBlobFiles bool
		AllowIndexing  bool
	}{fs, ids, allowBlobFiles, allowIndexing})
	if err != nil {
		return nil, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, databaseError(err)
	}
	defer tx.Rollback(ctx)
	value, err := filesystemForUpdate(ctx, tx, fs)
	if err != nil {
		return nil, err
	}
	if value.State != "active" {
		return nil, apperr.New(apperr.Conflict, "FILESYSTEM_DELETING", "filesystem is not active")
	}
	result := make([]Scope, 0, len(ids))
	for _, id := range ids {
		root := uuid.Must(uuid.NewV7())
		changed, err := tx.Exec(ctx, `INSERT INTO scopes(id,filesystem_id,root_id,allow_blob_files,allow_indexing) VALUES($1,$2,$3,$4,$5) ON CONFLICT(id) DO NOTHING`, id, fs, root, allowBlobFiles, allowIndexing)
		if err != nil {
			return nil, databaseError(err)
		}
		if changed.RowsAffected() == 1 {
			if _, err = tx.Exec(ctx, `INSERT INTO nodes(id,scope_id,name,kind) VALUES($1,$2,'root','directory')`, root, id); err != nil {
				return nil, databaseError(err)
			}
			session := session{tx: tx, filesystemID: fs, maxNodes: s.MaxNodes}
			if err = session.addNodes(ctx, 1); err != nil {
				return nil, err
			}
		}
		var scope Scope
		if err = tx.QueryRow(ctx, `SELECT id,filesystem_id,root_id,state,allow_blob_files,allow_indexing FROM scopes WHERE id=$1`, id).Scan(&scope.ID, &scope.FilesystemID, &scope.RootID, &scope.State, &scope.AllowBlobFiles, &scope.AllowIndexing); err != nil {
			return nil, databaseError(err)
		}
		if scope.FilesystemID != fs || scope.State != "active" || scope.AllowBlobFiles != allowBlobFiles || scope.AllowIndexing != allowIndexing {
			return nil, apperr.New(apperr.Precondition, "SCOPE_CONFLICT", "scope input conflicts")
		}
		result = append(result, scope)
	}
	if err = receipt(ctx, tx, caller, "create-scopes", key, hash, &result); err != nil {
		return nil, err
	}
	return result, databaseError(tx.Commit(ctx))
}

func (s *Store) PruneReceipts(ctx context.Context) error {
	_, err := s.DB.Exec(ctx, `DELETE FROM idempotency_keys WHERE (scope,operation,request_key) IN
		(SELECT scope,operation,request_key FROM idempotency_keys WHERE expires_at<=now() ORDER BY expires_at LIMIT 100)`)
	if err != nil {
		return databaseError(err)
	}
	return s.pruneDeletedStorage(ctx)
}

// Retain storage identity while transfers or object cleanup still reference it.
func (s *Store) pruneDeletedStorage(ctx context.Context) error {
	rows, err := s.DB.Query(ctx, `SELECT id FROM scopes WHERE state='deleted' ORDER BY id LIMIT 64`)
	if err != nil {
		return databaseError(err)
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return databaseError(err)
	}
	for _, id := range ids {
		if err = s.removeGraphResource(ctx, "scope", id); err != nil {
			return err
		}
		if _, err = s.DB.Exec(ctx, `DELETE FROM uploads WHERE scope_id=$1 AND (state='finalized' OR state='aborted' AND multipart_id IS NULL) AND (transfer_deadline IS NULL OR transfer_deadline<now()-interval '15 minutes')`, id); err != nil {
			return databaseError(err)
		}
		if _, err = s.DB.Exec(ctx, `DELETE FROM scopes WHERE id=$1 AND state='deleted' AND NOT EXISTS(SELECT 1 FROM uploads WHERE scope_id=$1)`, id); err != nil {
			return databaseError(err)
		}
	}
	rows, err = s.DB.Query(ctx, `SELECT id FROM filesystems WHERE state='deleted' ORDER BY id LIMIT 64`)
	if err != nil {
		return databaseError(err)
	}
	ids, err = pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return databaseError(err)
	}
	for _, id := range ids {
		if err = s.removeGraphResource(ctx, "filesystem", id); err != nil {
			return err
		}
		if _, err = s.DB.Exec(ctx, `DELETE FROM object_deletions WHERE filesystem_id=$1 AND state='deleted' AND NOT ambiguous_write AND open_writes=0`, id); err != nil {
			return databaseError(err)
		}
		if _, err = s.DB.Exec(ctx, `DELETE FROM filesystems WHERE id=$1 AND state='deleted' AND NOT EXISTS(SELECT 1 FROM scopes WHERE filesystem_id=$1) AND NOT EXISTS(SELECT 1 FROM object_deletions WHERE filesystem_id=$1)`, id); err != nil {
			return databaseError(err)
		}
	}
	return nil
}
