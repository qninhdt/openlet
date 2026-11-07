package filesystem

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"strings"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/packages/go/apperr"
)

type ProcessingOutput struct {
	Path       string  `json:"path"`
	Storage    string  `json:"storage"`
	SizeBytes  *int64  `json:"size_bytes,string"`
	ContentMD5 *string `json:"content_md5,omitempty"`
}

type OutputScope struct {
	Source   Generation
	Stage    string
	UploadID uuid.UUID
}

func (s OutputScope) access() (uploadAccess, error) {
	if err := s.Source.validate(); err != nil {
		return uploadAccess{}, err
	}
	if s.UploadID == uuid.Nil || (s.Stage != "parse" && s.Stage != "enrichment") {
		return uploadAccess{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid output scope")
	}
	return uploadAccess{source: &s.Source, stage: s.Stage}, nil
}

func (s *session) validateProcessing(ctx context.Context, a Generation, stage string) (processingState, error) {
	p, err := s.currentProcessing(ctx, a)
	if err != nil {
		return p, err
	}
	if _, err = s.processingSource(ctx, p); err != nil {
		return p, err
	}
	switch stage {
	case "parse":
	case "enrichment":
		if p.publication != "parsed" && p.publication != "enriched" && p.publication != "ready" && p.publication != "index_failed" {
			return p, uploadState("PARSE_NOT_COMPLETE")
		}
	default:
		return p, apperr.New(apperr.Invalid, "VALIDATION", "invalid processing stage")
	}
	return p, err
}

func relativeArtifactPath(path string) error {
	if path == "" || len(path) > 4096 || strings.Contains(path, `\`) || strings.Count(path, "/")+1 > maxDepth {
		return apperr.New(apperr.Invalid, "VALIDATION", "invalid artifact relative path")
	}
	for _, part := range strings.Split(path, "/") {
		if err := ValidateName(part); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) PrepareParseOutput(ctx context.Context, a Generation, output ProcessingOutput) (Upload, error) {
	return s.prepareProcessingOutput(ctx, a, "parse", output)
}

func (s *Store) prepareProcessingOutput(ctx context.Context, a Generation, stage string, output ProcessingOutput) (Upload, error) {
	if err := a.validate(); err != nil {
		return Upload{}, err
	}
	session, err := s.processingSession(ctx, a, false)
	if err != nil {
		return Upload{}, err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.validateProcessing(ctx, a, stage)
	if err != nil {
		return Upload{}, err
	}
	if stage == "parse" && p.publication != "pending" || stage == "enrichment" && p.publication != "parsed" {
		return Upload{}, uploadState("PROCESSING_NOT_ACTIVE")
	}
	id, err := session.insertProcessingOutput(ctx, s, a, stage, output)
	if err != nil {
		return Upload{}, err
	}
	if err = session.tx.Commit(ctx); err != nil {
		return Upload{}, databaseError(err)
	}
	return s.prepareUpload(ctx, session.scopeID, id, uploadAccess{source: &a, stage: stage})
}

func (s *session) insertProcessingOutput(ctx context.Context, store *Store, a Generation, stage string, output ProcessingOutput) (uuid.UUID, error) {
	if err := relativeArtifactPath(output.Path); err != nil {
		return uuid.Nil, err
	}
	if output.SizeBytes == nil || *output.SizeBytes < 0 {
		return uuid.Nil, apperr.New(apperr.Invalid, "VALIDATION", "nonnegative output size required")
	}
	encoded, err := json.Marshal(output)
	if err != nil {
		return uuid.Nil, err
	}
	size := *output.SizeBytes
	if size > store.ProcessingMaxOutputBytes {
		return uuid.Nil, uploadState("RESOURCE_LIMIT")
	}
	if size > store.MaxFileBytes {
		return uuid.Nil, apperr.New(apperr.Limit, "REQUEST_LIMIT", "file exceeds maximum")
	}
	transport := output.Storage
	var partSize *int64
	var candidate *string
	switch transport {
	case "inline":
		if size > store.InlineLimit {
			return uuid.Nil, apperr.New(apperr.Limit, "REQUEST_LIMIT", "inline bytes exceed limit")
		}
		if output.ContentMD5 != nil {
			return uuid.Nil, apperr.New(apperr.Invalid, "VALIDATION", "inline output has no Content-MD5")
		}
	case "object":
		if !s.allowBlobFiles {
			return uuid.Nil, apperr.New(apperr.Invalid, "BLOB_FILES_DISABLED", "scope requires inline processing outputs")
		}
		if store.Storage == nil || store.MultipartThreshold <= 0 || store.MultipartPartBytes < 5242880 {
			return uuid.Nil, storageError(ctx, storage.ErrUnavailable)
		}
		if size < store.MultipartThreshold {
			transport = "single"
			if output.ContentMD5 == nil {
				return uuid.Nil, apperr.New(apperr.Invalid, "VALIDATION", "Content-MD5 required")
			}
			digest, e := base64.StdEncoding.DecodeString(*output.ContentMD5)
			if e != nil || len(digest) != 16 || base64.StdEncoding.EncodeToString(digest) != *output.ContentMD5 {
				return uuid.Nil, apperr.New(apperr.Invalid, "VALIDATION", "invalid Content-MD5")
			}
		} else {
			transport = "multipart"
			if output.ContentMD5 != nil || 1+(size-1)/store.MultipartPartBytes > 10000 {
				return uuid.Nil, apperr.New(apperr.Invalid, "VALIDATION", "invalid multipart metadata")
			}
			partSize = &store.MultipartPartBytes
		}
	default:
		return uuid.Nil, apperr.New(apperr.Invalid, "VALIDATION", "invalid output storage")
	}
	id := uuid.Must(uuid.NewV7())
	if transport != "inline" {
		key := "objects/" + s.filesystemID.String() + "/" + id.String()
		candidate = &key
	}
	_, err = s.tx.Exec(ctx, `INSERT INTO uploads(id,scope_id,input,candidate_key,transport,expected_size,content_md5,part_size,
 processing_file_id,processing_generation,relative_path,processing_stage)
 VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)`, id, s.scopeID, encoded, candidate, transport, size, output.ContentMD5, partSize, a.FileID, a.Generation, output.Path, stage)
	return id, databaseError(err)
}

func (s *Store) GetOutputUpload(ctx context.Context, scope OutputScope) (Upload, error) {
	access, err := scope.access()
	if err != nil {
		return Upload{}, err
	}
	session, err := s.processingSession(ctx, scope.Source, false)
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
	session, err := s.processingSession(ctx, scope.Source, false)
	if err != nil {
		return nil, err
	}
	scopeID := session.scopeID
	if err = session.tx.Rollback(ctx); err != nil {
		return nil, databaseError(err)
	}
	return s.getUploadParts(ctx, scopeID, scope.UploadID, access, numbers)
}

func (s *Store) CompleteOutputUpload(ctx context.Context, scope OutputScope, parts []storage.PartReceipt) (Upload, error) {
	access, err := scope.access()
	if err != nil {
		return Upload{}, err
	}
	session, err := s.processingSession(ctx, scope.Source, false)
	if err != nil {
		return Upload{}, err
	}
	scopeID := session.scopeID
	if err = session.tx.Rollback(ctx); err != nil {
		return Upload{}, databaseError(err)
	}
	if _, err = s.completeUpload(ctx, scopeID, scope.UploadID, access, parts); err != nil {
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
		return Upload{}, apperr.New(apperr.Limit, "REQUEST_LIMIT", "inline bytes exceed limit")
	}
	session, err := s.processingSession(ctx, scope.Source, false)
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
		return Upload{}, apperr.New(apperr.Invalid, "VALIDATION", "inline size differs from prepared size")
	}
	if err = session.validateInlineText(content); err != nil {
		return Upload{}, err
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
	_, err = session.tx.Exec(ctx, `UPDATE uploads SET inline_bytes=$2,updated_at=now() WHERE id=$1`, scope.UploadID, content)
	if err != nil {
		return Upload{}, databaseError(err)
	}
	return upload, databaseError(session.tx.Commit(ctx))
}
