package filesystem

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"google.golang.org/grpc/codes"
	"openlet/apps/letfs/internal/storage"
	"openlet/packages/go/rpc"
)

type ProcessingOutput struct {
	Path       string  `json:"path"`
	Storage    string  `json:"storage"`
	SizeBytes  *int64  `json:"size_bytes,string"`
	ContentMD5 *string `json:"content_md5,omitempty"`
}

type OutputScope struct {
	Attempt  ProcessingAttempt
	Stage    string
	UploadID uuid.UUID
}

func (s OutputScope) access() (uploadAccess, error) {
	if err := s.Attempt.validate(); err != nil {
		return uploadAccess{}, err
	}
	if s.UploadID == uuid.Nil || (s.Stage != "parse" && s.Stage != "enrichment") {
		return uploadAccess{}, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid output scope")
	}
	return uploadAccess{attempt: &s.Attempt, stage: s.Stage}, nil
}

func (s *session) validateProcessing(ctx context.Context, a ProcessingAttempt, stage string) (processingState, error) {
	p, err := s.currentProcessing(ctx, a.Source)
	if err != nil {
		return p, err
	}
	if _, err = s.processingSource(ctx, p); err != nil {
		return p, err
	}
	switch stage {
	case "parse":
		if p.publication == "pending" {
			err = p.checkAttempt(a)
		}
	case "enrichment":
		if p.publication != "parsed" && p.publication != "ready" {
			return p, uploadState("PARSE_NOT_COMPLETE")
		}
		if p.publication != "ready" {
			err = p.checkAttempt(a)
		}
	default:
		return p, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid processing stage")
	}
	return p, err
}

func relativeArtifactPath(path string) error {
	if path == "" || len(path) > 4096 || strings.Contains(path, `\`) || strings.Count(path, "/")+1 > maxDepth {
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid artifact relative path")
	}
	for _, part := range strings.Split(path, "/") {
		if err := ValidateName(part); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) PrepareParseOutput(ctx context.Context, a ProcessingAttempt, output ProcessingOutput) (Upload, error) {
	return s.prepareProcessingOutput(ctx, a, "parse", output)
}

func (s *Store) prepareProcessingOutput(ctx context.Context, a ProcessingAttempt, stage string, output ProcessingOutput) (Upload, error) {
	if err := a.validate(); err != nil {
		return Upload{}, err
	}
	session, err := s.processingSession(ctx, a.Source, false)
	if err != nil {
		return Upload{}, err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.validateProcessing(ctx, a, stage)
	if err != nil {
		return Upload{}, err
	}
	if stage == "parse" && p.publication != "pending" || stage == "enrichment" && p.publication == "ready" {
		return Upload{}, uploadState("PROCESSING_NOT_ACTIVE")
	}
	id, err := session.insertProcessingOutput(ctx, s, a, stage, p, output)
	if err != nil {
		return Upload{}, err
	}
	if err = session.tx.Commit(ctx); err != nil {
		return Upload{}, databaseError(err)
	}
	return s.prepareUpload(ctx, session.fs, id, uploadAccess{attempt: &a, stage: stage})
}

func (s *session) insertProcessingOutput(ctx context.Context, store *Store, a ProcessingAttempt, stage string, p processingState, output ProcessingOutput) (uuid.UUID, error) {
	if err := relativeArtifactPath(output.Path); err != nil {
		return uuid.Nil, err
	}
	if output.SizeBytes == nil || *output.SizeBytes < 0 {
		return uuid.Nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "nonnegative output size required")
	}
	encoded, err := json.Marshal(output)
	if err != nil {
		return uuid.Nil, err
	}
	var id uuid.UUID
	var saved []byte
	err = s.tx.QueryRow(ctx, `SELECT id,input FROM uploads WHERE processing_file_id=$1 AND processing_generation=$2 AND processing_attempt=$3 AND processing_stage=$4 AND relative_path=$5`, a.Source.FileID, a.Source.Generation, a.Number, stage, output.Path).Scan(&id, &saved)
	if err == nil {
		var old ProcessingOutput
		if json.Unmarshal(saved, &old) != nil {
			return uuid.Nil, uploadState("INVALID_UPLOAD_STATE")
		}
		oldHash, e := fingerprint(old)
		if e != nil {
			return uuid.Nil, e
		}
		newHash, e := fingerprint(output)
		if e != nil {
			return uuid.Nil, e
		}
		if oldHash != newHash {
			return uuid.Nil, uploadState("IDEMPOTENCY_CONFLICT")
		}
		return id, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return uuid.Nil, databaseError(err)
	}
	var count, total int64
	err = s.tx.QueryRow(ctx, `SELECT count(*),coalesce(sum(expected_size),0)::bigint FROM uploads WHERE processing_file_id=$1 AND processing_generation=$2 AND processing_attempt=$3 AND processing_stage=$4`, a.Source.FileID, a.Source.Generation, a.Number, stage).Scan(&count, &total)
	if err != nil {
		return uuid.Nil, databaseError(err)
	}
	size := *output.SizeBytes
	if count >= store.ProcessingMaxOutputs || size > store.ProcessingMaxOutputBytes-total {
		return uuid.Nil, uploadState("RESOURCE_LIMIT")
	}
	if size > store.MaxFileBytes {
		return uuid.Nil, rpc.Fault(codes.ResourceExhausted, "REQUEST_LIMIT", "file exceeds maximum")
	}
	transport := output.Storage
	var partSize *int64
	var candidate *string
	switch transport {
	case "inline":
		if size > store.InlineLimit {
			return uuid.Nil, rpc.Fault(codes.ResourceExhausted, "REQUEST_LIMIT", "inline bytes exceed limit")
		}
		if output.ContentMD5 != nil {
			return uuid.Nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "inline output has no Content-MD5")
		}
	case "object":
		if store.Storage == nil || store.MultipartThreshold <= 0 || store.MultipartPartBytes < 5242880 {
			return uuid.Nil, storageError(ctx, storage.ErrUnavailable)
		}
		if size < store.MultipartThreshold {
			transport = "single"
			if output.ContentMD5 == nil {
				return uuid.Nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "Content-MD5 required")
			}
			digest, e := base64.StdEncoding.DecodeString(*output.ContentMD5)
			if e != nil || len(digest) != 16 || base64.StdEncoding.EncodeToString(digest) != *output.ContentMD5 {
				return uuid.Nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid Content-MD5")
			}
		} else {
			transport = "multipart"
			if output.ContentMD5 != nil || 1+(size-1)/store.MultipartPartBytes > 10000 {
				return uuid.Nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid multipart metadata")
			}
			partSize = &store.MultipartPartBytes
		}
	default:
		return uuid.Nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid output storage")
	}
	if p.actor == nil {
		return uuid.Nil, uploadState("INVALID_SOURCE_IDENTITY")
	}
	id = uuid.Must(uuid.NewV7())
	if transport != "inline" {
		key := "objects/" + s.bucket.String() + "/" + id.String()
		candidate = &key
	}
	_, err = s.tx.Exec(ctx, `INSERT INTO uploads(id,filesystem_id,bucket_id,actor_id,input,candidate_key,transport,expected_size,content_md5,part_size,
 processing_file_id,processing_generation,processing_attempt,processing_attempt_id,relative_path,processing_stage)
 VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)`, id, s.fs, s.bucket, *p.actor, encoded, candidate, transport, size, output.ContentMD5, partSize, a.Source.FileID, a.Source.Generation, a.Number, a.ID, output.Path, stage)
	return id, databaseError(err)
}

func (s *Store) GetOutputUpload(ctx context.Context, scope OutputScope) (Upload, error) {
	access, err := scope.access()
	if err != nil {
		return Upload{}, err
	}
	session, err := s.processingSession(ctx, scope.Attempt.Source, false)
	if err != nil {
		return Upload{}, err
	}
	defer session.tx.Rollback(ctx)
	return session.loadUpload(ctx, scope.UploadID, access)
}

func (s *Store) GetOutputUploadParts(ctx context.Context, scope OutputScope, numbers []int32) ([]UploadPart, error) {
	access, err := scope.access()
	if err != nil {
		return nil, err
	}
	session, err := s.processingSession(ctx, scope.Attempt.Source, false)
	if err != nil {
		return nil, err
	}
	fs := session.fs
	if err = session.tx.Rollback(ctx); err != nil {
		return nil, databaseError(err)
	}
	return s.getUploadParts(ctx, fs, scope.UploadID, access, numbers)
}

func (s *Store) CompleteOutputUpload(ctx context.Context, scope OutputScope, parts []storage.PartReceipt) (Upload, error) {
	access, err := scope.access()
	if err != nil {
		return Upload{}, err
	}
	session, err := s.processingSession(ctx, scope.Attempt.Source, false)
	if err != nil {
		return Upload{}, err
	}
	fs := session.fs
	if err = session.tx.Rollback(ctx); err != nil {
		return Upload{}, databaseError(err)
	}
	if _, err = s.completeUpload(ctx, fs, scope.UploadID, access, parts); err != nil {
		return Upload{}, err
	}
	return s.GetOutputUpload(ctx, scope)
}

func (s *Store) WriteOutputBytes(ctx context.Context, scope OutputScope, content []byte) (Upload, error) {
	access, err := scope.access()
	if err != nil {
		return Upload{}, err
	}
	if int64(len(content)) > s.InlineLimit {
		return Upload{}, rpc.Fault(codes.ResourceExhausted, "REQUEST_LIMIT", "inline bytes exceed limit")
	}
	session, err := s.processingSession(ctx, scope.Attempt.Source, false)
	if err != nil {
		return Upload{}, err
	}
	defer session.tx.Rollback(ctx)
	upload, err := session.loadUpload(ctx, scope.UploadID, access)
	if err != nil {
		return Upload{}, err
	}
	if upload.Transport != "inline" {
		return Upload{}, uploadState("DIRECT_UPLOAD_REQUIRED")
	}
	if int64(len(content)) != upload.SizeBytes {
		return Upload{}, rpc.Fault(codes.InvalidArgument, "VALIDATION", "inline size differs from prepared size")
	}
	digest := sha256.Sum256(content)
	hash := hex.EncodeToString(digest[:])
	if upload.sha256 != nil && *upload.sha256 != hash {
		return Upload{}, uploadState("IDEMPOTENCY_CONFLICT")
	}
	if upload.State == "finalized" {
		return upload, nil
	}
	if err = upload.active(); err != nil {
		return Upload{}, err
	}
	if content == nil {
		content = []byte{}
	}
	_, err = session.tx.Exec(ctx, `UPDATE uploads SET size_bytes=$2,sha256=$3,inline_bytes=$4,updated_at=now() WHERE id=$1`, scope.UploadID, upload.SizeBytes, hash, content)
	if err != nil {
		return Upload{}, databaseError(err)
	}
	return upload, databaseError(session.tx.Commit(ctx))
}
