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
	"github.com/qninhdt/openlet/apps/letfs/internal/search"
	"github.com/qninhdt/openlet/apps/letfs/internal/storage"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"golang.org/x/sync/semaphore"
	"google.golang.org/grpc/codes"
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

type Bucket struct {
	ID         uuid.UUID `json:"id"`
	LimitBytes int64     `json:"limit_bytes,string"`
	UsedBytes  int64     `json:"used_bytes,string"`
	State      string    `json:"state"`
}

type Filesystem struct {
	ID       uuid.UUID  `json:"id"`
	BucketID uuid.UUID  `json:"bucket_id"`
	RootID   *uuid.UUID `json:"root_id"`
	State    string     `json:"state"`
}

type CreateBucket struct {
	ID         uuid.UUID `json:"id"`
	LimitBytes int64     `json:"limit_bytes"`
}

type CreateFilesystem struct {
	ID       uuid.UUID `json:"id"`
	BucketID uuid.UUID `json:"bucket_id"`
	RootName string    `json:"root_name"`
}

func service(ctx context.Context) (string, error) {
	principal, ok := identity.FromContext(ctx)
	if !ok || principal.Gateway || principal.Service == "" {
		return "", rpc.Fault(codes.PermissionDenied, "FORBIDDEN", "service authority required")
	}
	return principal.Service, nil
}

func requestIdentity(id, key uuid.UUID) error {
	if id == uuid.Nil || id.Version() != 7 || key == uuid.Nil {
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "stable UUIDv7 identity and request key required")
	}
	return nil
}

func ValidateName(name string) error {
	if !utf8.ValidString(name) || len(name) == 0 || len(name) > 255 || name == "." || name == ".." || strings.ContainsAny(name, "/\x00") {
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid name")
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
		return rpc.Fault(codes.Aborted, "IDEMPOTENCY_CONFLICT", "request key was used for different input")
	}
	if err != nil {
		return err
	}
	return json.Unmarshal(saved, result)
}

func (s *Store) CreateBucket(ctx context.Context, key uuid.UUID, input CreateBucket) (Bucket, error) {
	var result Bucket
	caller, err := service(ctx)
	if err != nil {
		return result, err
	}
	if err = requestIdentity(input.ID, key); err != nil {
		return result, err
	}
	if input.LimitBytes < 0 {
		return result, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid byte limit")
	}
	hash, err := fingerprint(input)
	if err != nil {
		return result, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return result, err
	}
	defer tx.Rollback(ctx)
	_, err = tx.Exec(ctx, `INSERT INTO quota_buckets(id,limit_bytes)
		VALUES($1,$2) ON CONFLICT(id) DO NOTHING`, input.ID, input.LimitBytes)
	if err != nil {
		return result, err
	}
	err = tx.QueryRow(ctx, `SELECT id,limit_bytes,used_bytes,state FROM quota_buckets WHERE id=$1 FOR UPDATE`, input.ID).
		Scan(&result.ID, &result.LimitBytes, &result.UsedBytes, &result.State)
	if err != nil {
		return result, err
	}
	if result.State != "active" {
		return Bucket{}, rpc.Fault(codes.FailedPrecondition, "SCOPE_CONFLICT", "resource scope or state conflicts")
	}
	if err = receipt(ctx, tx, caller, "create-bucket", key, hash, &result); err != nil {
		return Bucket{}, err
	}
	return result, tx.Commit(ctx)
}

func bucketForUpdate(ctx context.Context, tx pgx.Tx, id uuid.UUID) (Bucket, error) {
	var result Bucket
	err := tx.QueryRow(ctx, `SELECT id,limit_bytes,used_bytes,state FROM quota_buckets WHERE id=$1 FOR UPDATE`, id).
		Scan(&result.ID, &result.LimitBytes, &result.UsedBytes, &result.State)
	if errors.Is(err, pgx.ErrNoRows) {
		return Bucket{}, rpc.Fault(codes.NotFound, "NOT_FOUND", "resource not found")
	}
	if err != nil {
		return Bucket{}, err
	}
	return result, nil
}

func (s *Store) CreateFilesystem(ctx context.Context, key uuid.UUID, input CreateFilesystem) (Filesystem, error) {
	var result Filesystem
	caller, err := service(ctx)
	if err != nil {
		return result, err
	}
	if err = requestIdentity(input.ID, key); err != nil {
		return result, err
	}
	if input.BucketID == uuid.Nil || input.BucketID.Version() != 7 || s.MaxNodes <= 0 {
		return result, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid filesystem limits or bucket")
	}
	if err = ValidateName(input.RootName); err != nil {
		return result, err
	}
	hash, err := fingerprint(input)
	if err != nil {
		return result, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return result, err
	}
	defer tx.Rollback(ctx)
	bucket, err := bucketForUpdate(ctx, tx, input.BucketID)
	if err != nil {
		return result, err
	}
	if bucket.State != "active" {
		return result, rpc.Fault(codes.FailedPrecondition, "SCOPE_CONFLICT", "bucket is not active")
	}
	root, err := uuid.NewV7()
	if err != nil {
		return result, err
	}
	inserted, err := tx.Exec(ctx, `INSERT INTO filesystems(id,bucket_id,root_id) VALUES($1,$2,$3) ON CONFLICT(id) DO NOTHING`, input.ID, input.BucketID, root)
	if err != nil {
		return result, err
	}
	if inserted.RowsAffected() == 1 {
		_, err = tx.Exec(ctx, `INSERT INTO nodes(id,filesystem_id,name,kind) VALUES($1,$2,$3,'directory')`, root, input.ID, input.RootName)
		if err != nil {
			return result, err
		}
	}
	err = tx.QueryRow(ctx, `SELECT id,bucket_id,root_id,state FROM filesystems WHERE id=$1 FOR UPDATE`, input.ID).
		Scan(&result.ID, &result.BucketID, &result.RootID, &result.State)
	if err != nil {
		return result, err
	}
	if result.BucketID != input.BucketID || result.State != "active" {
		return Filesystem{}, rpc.Fault(codes.FailedPrecondition, "SCOPE_CONFLICT", "resource scope or state conflicts")
	}
	if err = receipt(ctx, tx, caller, "create-filesystem", key, hash, &result); err != nil {
		return Filesystem{}, err
	}
	return result, tx.Commit(ctx)
}

func (s *Store) FreezeBucket(ctx context.Context, key, id uuid.UUID) (Bucket, error) {
	var result Bucket
	caller, err := service(ctx)
	if err != nil {
		return result, err
	}
	if err = requestIdentity(id, key); err != nil {
		return result, err
	}
	hash, err := fingerprint(id)
	if err != nil {
		return result, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return result, err
	}
	defer tx.Rollback(ctx)
	_, err = tx.Exec(ctx, `INSERT INTO quota_buckets(id,limit_bytes,state) VALUES($1,0,'frozen') ON CONFLICT(id) DO NOTHING`, id)
	if err != nil {
		return result, err
	}
	result, err = bucketForUpdate(ctx, tx, id)
	if err != nil {
		return result, err
	}
	if result.State == "active" {
		_, err = tx.Exec(ctx, `UPDATE quota_buckets SET state='frozen' WHERE id=$1`, id)
		if err != nil {
			return result, err
		}
		result.State = "frozen"
	}
	if err = receipt(ctx, tx, caller, "freeze-bucket", key, hash, &result); err != nil {
		return Bucket{}, err
	}
	return result, tx.Commit(ctx)
}

func (s *Store) ListBucketFilesystems(ctx context.Context, id, after uuid.UUID) ([]uuid.UUID, error) {
	_, err := service(ctx)
	if err != nil {
		return nil, err
	}
	if id == uuid.Nil || id.Version() != 7 {
		return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid bucket")
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return nil, err
	}
	defer tx.Rollback(ctx)
	bucket, err := bucketForUpdate(ctx, tx, id)
	if err != nil {
		return nil, err
	}
	if bucket.State != "frozen" && bucket.State != "deleted" {
		return nil, rpc.Fault(codes.FailedPrecondition, "BUCKET_NOT_FROZEN", "bucket must be frozen")
	}
	rows, err := tx.Query(ctx, `SELECT id FROM filesystems WHERE bucket_id=$1 AND state!='deleted' AND id>$2 ORDER BY id LIMIT 64`, id, after)
	if err != nil {
		return nil, err
	}
	result, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return nil, err
	}
	return result, tx.Commit(ctx)
}

func (s *Store) CompleteBucketDeletion(ctx context.Context, key, id uuid.UUID) (Bucket, error) {
	var result Bucket
	caller, err := service(ctx)
	if err != nil {
		return result, err
	}
	if err = requestIdentity(id, key); err != nil {
		return result, err
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return result, err
	}
	defer tx.Rollback(ctx)
	result, err = bucketForUpdate(ctx, tx, id)
	if err != nil {
		return result, err
	}
	changed, err := tx.Exec(ctx, `UPDATE quota_buckets b SET state='deleted' WHERE id=$1 AND state IN ('frozen','deleted') AND used_bytes=0
		AND NOT EXISTS(SELECT 1 FROM filesystems WHERE bucket_id=b.id AND state!='deleted')
		AND NOT EXISTS(SELECT 1 FROM uploads WHERE bucket_id=b.id AND state IN ('open','completing'))`, id)
	if err != nil {
		return result, err
	}
	if changed.RowsAffected() != 1 {
		return Bucket{}, rpc.Fault(codes.FailedPrecondition, "DELETION_INCOMPLETE", "bucket deletion incomplete")
	}
	result.State = "deleted"
	hash, err := fingerprint(id)
	if err != nil {
		return Bucket{}, err
	}
	if err = receipt(ctx, tx, caller, "delete-bucket", key, hash, &result); err != nil {
		return Bucket{}, err
	}
	_, err = tx.Exec(ctx, `UPDATE idempotency_keys SET expires_at=COALESCE(expires_at,now()+interval '24 hours')
		WHERE scope=$1 AND result->>'id'=$2 AND operation IN ('create-bucket','freeze-bucket','delete-bucket')`, "service:"+caller, id.String())
	if err != nil {
		return Bucket{}, err
	}
	return result, tx.Commit(ctx)
}

func (s *Store) PruneReceipts(ctx context.Context) error {
	_, err := s.DB.Exec(ctx, `DELETE FROM idempotency_keys WHERE (scope,operation,request_key) IN
		(SELECT scope,operation,request_key FROM idempotency_keys WHERE expires_at<=now() ORDER BY expires_at LIMIT 100)`)
	return err
}

func (s *Store) ReleaseProvisioning(ctx context.Context, bucketID, filesystemID, rootID uuid.UUID) error {
	caller, err := service(ctx)
	if err != nil {
		return err
	}
	if bucketID == uuid.Nil || bucketID.Version() != 7 || filesystemID == uuid.Nil || rootID == uuid.Nil {
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "bucket, filesystem and root identity required")
	}
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err = bucketForUpdate(ctx, tx, bucketID); err != nil {
		return err
	}
	var valid bool
	err = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM filesystems WHERE id=$1 AND bucket_id=$2 AND (root_id=$3 OR state='deleted'))`, filesystemID, bucketID, rootID).Scan(&valid)
	if err != nil {
		return err
	}
	if !valid {
		return rpc.Fault(codes.FailedPrecondition, "SCOPE_CONFLICT", "resource scope or state conflicts")
	}
	_, err = tx.Exec(ctx, `UPDATE idempotency_keys SET expires_at=COALESCE(expires_at,now()+interval '24 hours')
		WHERE scope=$1 AND ((operation='create-bucket' AND result->>'id'=$2) OR (operation='create-filesystem' AND result->>'id'=$3))`, "service:"+caller, bucketID.String(), filesystemID.String())
	if err != nil {
		return err
	}
	return tx.Commit(ctx)
}
