package filesystem

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type UploadDestination struct {
	Parent Locator `json:"parent"`
	Name   string  `json:"name"`
}

type UploadReplacement struct {
	Locator  Locator `json:"locator"`
	Revision *int64  `json:"revision,omitempty,string"`
}

type UploadCreation struct {
	SizeBytes   *int64             `json:"size_bytes,string"`
	MediaType   string             `json:"media_type"`
	ContentMD5  *string            `json:"content_md5,omitempty"`
	Destination *UploadDestination `json:"destination,omitempty"`
	Replacement *UploadReplacement `json:"replacement,omitempty"`
}

type savedUpload struct {
	Input UploadCreation `json:"input"`
}

type UploadPublication struct {
	NodeID   uuid.UUID `json:"node_id"`
	Status   string    `json:"status"`
	Revision int64     `json:"revision,string"`
}

type Upload struct {
	ID                    uuid.UUID
	State, Transport      string
	ExpiresAt             time.Time
	SizeBytes             int64
	PartSize              *int64
	Transfer              *storage.SignedUpload
	Publication           *UploadPublication
	input                 []byte
	key, md5, multipartID *string
	parts                 []byte
	content               []byte
}

type uploadAccess struct {
	actor  uuid.UUID
	source *Generation
	stage  string
}

func uploadState(code string) error {
	return apperr.New(apperr.Conflict, code, "upload conflicts with current state")
}

func (u Upload) active() error {
	if (u.State != "open" && u.State != "completing") || !u.ExpiresAt.After(time.Now()) {
		return uploadState("UPLOAD_NOT_ACTIVE")
	}
	return nil
}

func (u Upload) PartCount() int32 {
	if u.PartSize == nil || *u.PartSize <= 0 || u.SizeBytes <= 0 {
		return 0
	}
	return int32(1 + (u.SizeBytes-1) / *u.PartSize)
}

func (s *session) loadUpload(ctx context.Context, id uuid.UUID, access uploadAccess) (Upload, error) {
	complete := false
	if access.source != nil {
		p, err := s.validateProcessing(ctx, *access.source, access.stage)
		if err != nil {
			return Upload{}, err
		}
		complete = p.publication != "pending"
		if access.stage == "enrichment" {
			complete = p.publication != "parsed"
		}
	}
	var result Upload
	var publication []byte
	var fileID *uuid.UUID
	var generation *int64
	var stage *string
	var actor *uuid.UUID
	err := s.tx.QueryRow(ctx, `SELECT id,state,transport,expires_at,expected_size,part_size,input,candidate_key,content_md5,multipart_id,completion_parts,result,
 inline_bytes,actor_id,processing_file_id,processing_generation,processing_stage
 FROM uploads WHERE id=$1 AND scope_id=$2 FOR UPDATE`, id, s.scopeID).
		Scan(&result.ID, &result.State, &result.Transport, &result.ExpiresAt, &result.SizeBytes, &result.PartSize, &result.input, &result.key, &result.md5, &result.multipartID, &result.parts, &publication,
			&result.content, &actor, &fileID, &generation, &stage)
	if err != nil {
		return Upload{}, databaseError(err)
	}
	permitted := actor != nil && *actor == access.actor && fileID == nil
	if a := access.source; a != nil {
		permitted = fileID != nil && *fileID == a.FileID && generation != nil && *generation == a.Generation &&
			stage != nil && *stage == access.stage
	}
	if !permitted {
		return Upload{}, apperr.New(apperr.Missing, "NOT_FOUND", "resource not found")
	}
	if complete && (result.State == "open" || result.State == "completing") {
		return Upload{}, uploadState("PROCESSING_NOT_ACTIVE")
	}
	if publication != nil && access.source == nil {
		if err = json.Unmarshal(publication, &result.Publication); err != nil {
			return Upload{}, uploadState("INVALID_UPLOAD_STATE")
		}
	}
	return result, nil
}

func (s *session) uploadTarget(ctx context.Context, saved savedUpload) (*Node, uuid.UUID, string, error) {
	input := saved.Input
	if (input.Replacement == nil) == (input.Destination == nil) {
		return nil, uuid.Nil, "", apperr.New(apperr.Invalid, "VALIDATION", "exactly one upload target required")
	}
	if input.Replacement != nil {
		r := input.Replacement
		node, err := s.resolveOne(ctx, r.Locator)
		if err != nil {
			return nil, uuid.Nil, "", err
		}
		if err = guard(r.Locator, node.ID, false); err != nil {
			return nil, uuid.Nil, "", err
		}
		if err = node.writable(); err != nil {
			return nil, uuid.Nil, "", err
		}
		if err = node.revision(r.Revision); err != nil {
			return nil, uuid.Nil, "", err
		}
		if node.Kind != "file" {
			return nil, uuid.Nil, "", apperr.New(apperr.Conflict, "NOT_FILE", "file required")
		}
		if node.ParentID == nil {
			return nil, uuid.Nil, "", apperr.New(apperr.Missing, "NOT_FOUND", "resource not found")
		}
		return &node, *node.ParentID, node.Name, nil
	}
	d := input.Destination
	parent, err := s.resolveOne(ctx, d.Parent)
	if err != nil {
		return nil, uuid.Nil, "", err
	}
	if err = guard(d.Parent, parent.ID, true); err != nil {
		return nil, uuid.Nil, "", err
	}
	if err = parent.writable(); err != nil {
		return nil, uuid.Nil, "", err
	}
	if err = parent.directory(); err != nil {
		return nil, uuid.Nil, "", err
	}
	if err = s.name(parent.ID, d.Name); err != nil {
		return nil, uuid.Nil, "", err
	}
	var exists bool
	if err = s.tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM nodes WHERE scope_id=$1 AND parent_id=$2 AND name=$3)`, s.scopeID, parent.ID, d.Name).Scan(&exists); err != nil {
		return nil, uuid.Nil, "", databaseError(err)
	}
	if exists {
		return nil, uuid.Nil, "", apperr.New(apperr.Exists, "NAME_CONFLICT", "name already exists")
	}
	depth, err := s.depth(ctx, parent.ID)
	if err != nil {
		return nil, uuid.Nil, "", err
	}
	if depth >= maxDepth {
		return nil, uuid.Nil, "", apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "tree depth limit exceeded")
	}
	return nil, parent.ID, d.Name, nil
}

func (s *session) uploadCapacity(ctx context.Context, maxOutstanding, maxBacklog int64) error {
	var outstanding, backlog int64
	err := s.tx.QueryRow(ctx, `SELECT
 (SELECT count(*) FROM uploads u JOIN scopes sc ON sc.id=u.scope_id WHERE sc.filesystem_id=$1 AND u.processing_file_id IS NULL AND u.state IN ('open','completing')),
 (SELECT count(*) FROM object_deletions WHERE filesystem_id=$1 AND (state!='deleted' OR ambiguous_write OR open_writes>0))`, s.filesystemID).Scan(&outstanding, &backlog)
	if err != nil {
		return databaseError(err)
	}
	if outstanding >= maxOutstanding || backlog >= maxBacklog {
		return apperr.New(apperr.Conflict, "RESOURCE_LIMIT", "outstanding operation limit exceeded")
	}
	return nil
}

func storageError(ctx context.Context, err error) error {
	if err == nil {
		return nil
	}
	if ctx.Err() != nil {
		return ctx.Err()
	}
	return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "object storage unavailable")
}

func (s *Store) CreateUpload(ctx context.Context, scopeID uuid.UUID, key uuid.UUID, input UploadCreation) (Upload, error) {
	actor, err := s.authorize(ctx, scopeID, "scope", authz.ScopeWrite)
	if err != nil {
		return Upload{}, err
	}
	if key == uuid.Nil || input.SizeBytes == nil || *input.SizeBytes < 0 || (input.Destination == nil) == (input.Replacement == nil) {
		return Upload{}, apperr.New(apperr.Invalid, "VALIDATION", "request key, size and one target required")
	}
	if err = mediaType(input.MediaType); err != nil {
		return Upload{}, err
	}
	saved := savedUpload{Input: input}
	hash, err := fingerprint(saved)
	if err != nil {
		return Upload{}, err
	}
	session, err := s.openSession(ctx, scopeID, true)
	if err != nil {
		return Upload{}, err
	}
	defer session.tx.Rollback(ctx)
	scope := "scope/" + scopeID.String() + "/actor/" + actor.String()
	if !session.allowBlobFiles {
		return Upload{}, apperr.New(apperr.Invalid, "BLOB_FILES_DISABLED", "scope does not allow blob files")
	}
	var oldHash string
	var receipt struct {
		ID uuid.UUID `json:"id"`
	}
	var result []byte
	err = session.tx.QueryRow(ctx, `SELECT request_hash,result FROM idempotency_keys WHERE scope=$1 AND operation='create-upload' AND request_key=$2 AND (expires_at IS NULL OR expires_at>now())`, scope, key.String()).Scan(&oldHash, &result)
	if err == nil {
		if oldHash != hash {
			return Upload{}, uploadState("IDEMPOTENCY_CONFLICT")
		}
		if err = json.Unmarshal(result, &receipt); err != nil {
			return Upload{}, uploadState("INVALID_RECEIPT")
		}
		if err = session.tx.Commit(ctx); err != nil {
			return Upload{}, databaseError(err)
		}
		return s.prepareUpload(ctx, scopeID, receipt.ID, uploadAccess{actor: actor})
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return Upload{}, databaseError(err)
	}
	if *input.SizeBytes > s.MaxFileBytes {
		return Upload{}, apperr.New(apperr.Limit, "REQUEST_LIMIT", "file exceeds maximum")
	}
	if s.Storage == nil || s.MultipartThreshold <= 0 || s.MultipartPartBytes < 5*1024*1024 {
		return Upload{}, storageError(ctx, storage.ErrUnavailable)
	}
	transport := "multipart"
	var partSize *int64
	if *input.SizeBytes < s.MultipartThreshold {
		transport = "single"
		if input.ContentMD5 == nil {
			return Upload{}, apperr.New(apperr.Invalid, "VALIDATION", "Content-MD5 required")
		}
		digest, err := base64.StdEncoding.DecodeString(*input.ContentMD5)
		if err != nil || len(digest) != 16 || base64.StdEncoding.EncodeToString(digest) != *input.ContentMD5 {
			return Upload{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid Content-MD5")
		}
	} else {
		if input.ContentMD5 != nil || 1+(*input.SizeBytes-1)/s.MultipartPartBytes > 10000 {
			return Upload{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid multipart metadata")
		}
		partSize = &s.MultipartPartBytes
	}
	if err = session.uploadCapacity(ctx, s.MaxOutstanding, s.MaxCleanupBacklog); err != nil {
		return Upload{}, err
	}
	if _, _, _, err = session.uploadTarget(ctx, saved); err != nil {
		return Upload{}, err
	}
	id := uuid.Must(uuid.NewV7())
	candidate := "objects/" + session.filesystemID.String() + "/" + id.String()
	encoded, err := json.Marshal(saved)
	if err != nil {
		return Upload{}, err
	}
	_, err = session.tx.Exec(ctx, `INSERT INTO uploads(id,scope_id,actor_id,input,candidate_key,transport,expected_size,content_md5,part_size) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)`, id, scopeID, actor, encoded, candidate, transport, *input.SizeBytes, input.ContentMD5, partSize)
	if err != nil {
		return Upload{}, databaseError(err)
	}
	result, err = json.Marshal(struct {
		ID uuid.UUID `json:"id"`
	}{id})
	if err != nil {
		return Upload{}, err
	}
	_, err = session.tx.Exec(ctx, `INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) VALUES($1,'create-upload',$2,$3,$4) ON CONFLICT(scope,operation,request_key) DO UPDATE SET request_hash=excluded.request_hash,result=excluded.result,expires_at=NULL WHERE idempotency_keys.expires_at<=now()`, scope, key.String(), hash, result)
	if err != nil {
		return Upload{}, databaseError(err)
	}
	if err = session.tx.Commit(ctx); err != nil {
		return Upload{}, databaseError(err)
	}
	return s.prepareUpload(ctx, scopeID, id, uploadAccess{actor: actor})
}

func (s *Store) GetUpload(ctx context.Context, scopeID, id uuid.UUID) (Upload, error) {
	actor, err := s.authorize(ctx, scopeID, "scope", authz.ScopeWrite)
	if err != nil {
		return Upload{}, err
	}
	session, err := s.openSession(ctx, scopeID, true)
	if err != nil {
		return Upload{}, err
	}
	defer session.tx.Rollback(ctx)
	return session.loadUpload(ctx, id, uploadAccess{actor: actor})
}

func (s *Store) signUpload(ctx context.Context, upload Upload, number *int32, processing bool) (storage.SignedUpload, error) {
	remaining := time.Until(upload.ExpiresAt).Truncate(time.Second)
	if remaining < time.Second {
		return storage.SignedUpload{}, uploadState("UPLOAD_NOT_ACTIVE")
	}
	if s.Storage == nil || upload.key == nil {
		return storage.SignedUpload{}, storageError(ctx, storage.ErrUnavailable)
	}
	lifetime := min(s.UploadLifetime, remaining)
	var signed storage.SignedUpload
	var err error
	if number == nil {
		if upload.md5 == nil {
			return storage.SignedUpload{}, uploadState("INVALID_UPLOAD_STATE")
		}
		sign := s.Storage.SignPut
		if processing {
			sign = s.Storage.ProcessorSignPut
		}
		signed, err = sign(ctx, *upload.key, upload.SizeBytes, *upload.md5, lifetime)
	} else {
		if upload.PartSize == nil || *number < 1 || *number > upload.PartCount() {
			return storage.SignedUpload{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid part number")
		}
		if upload.multipartID == nil {
			return storage.SignedUpload{}, uploadState("UPLOAD_NOT_READY")
		}
		size := min(*upload.PartSize, upload.SizeBytes-int64(*number-1)**upload.PartSize)
		sign := s.Storage.SignPart
		if processing {
			sign = s.Storage.ProcessorSignPart
		}
		signed, err = sign(ctx, *upload.key, *upload.multipartID, *number, size, lifetime)
	}
	return signed, storageError(ctx, err)
}

func (s *session) recordCapability(ctx context.Context, id uuid.UUID, expires time.Time, grace time.Duration) error {
	_, err := s.tx.Exec(ctx, `UPDATE uploads SET transfer_deadline=greatest(transfer_deadline,$2),updated_at=now() WHERE id=$1`, id, expires.Add(grace))
	return databaseError(err)
}

func (s *Store) prepareUpload(ctx context.Context, scopeID, id uuid.UUID, access uploadAccess) (Upload, error) {
	session, err := s.openSession(ctx, scopeID, true)
	if err != nil {
		return Upload{}, err
	}
	defer session.tx.Rollback(ctx)
	upload, err := session.loadUpload(ctx, id, access)
	if err != nil {
		return Upload{}, err
	}
	if upload.State != "open" || !upload.ExpiresAt.After(time.Now()) {
		return upload, nil
	}
	if upload.Transport == "single" {
		signed, err := s.signUpload(ctx, upload, nil, access.source != nil)
		if err != nil {
			return Upload{}, err
		}
		if err = session.recordCapability(ctx, id, signed.ExpiresAt, s.UploadTransferGrace); err != nil {
			return Upload{}, err
		}
		upload.Transfer = &signed
	}
	if err = session.tx.Commit(ctx); err != nil {
		return Upload{}, databaseError(err)
	}
	if upload.Transport == "multipart" && upload.multipartID == nil {
		remote, err := s.Storage.CreateMultipart(ctx, *upload.key)
		if err != nil {
			return Upload{}, storageError(ctx, err)
		}
		winner, err := s.saveMultipart(ctx, scopeID, id, access, remote)
		// An unknown commit may have persisted this remote as the winner.
		if err != nil {
			return Upload{}, err
		}
		if winner != remote {
			if err = s.Storage.AbortMultipart(ctx, *upload.key, remote); err != nil && !errors.Is(err, storage.ErrNotFound) {
				return Upload{}, storageError(ctx, err)
			}
		}
	}
	return upload, nil
}

func (s *Store) saveMultipart(ctx context.Context, scopeID, id uuid.UUID, access uploadAccess, remote string) (string, error) {
	session, err := s.openSession(ctx, scopeID, true)
	if err != nil {
		return "", err
	}
	defer session.tx.Rollback(ctx)
	upload, err := session.loadUpload(ctx, id, access)
	if err != nil {
		return "", err
	}
	if err = upload.active(); err != nil {
		return "", err
	}
	winner := remote
	if upload.multipartID != nil {
		winner = *upload.multipartID
	} else {
		_, err = session.tx.Exec(ctx, `UPDATE uploads SET multipart_id=$2,updated_at=now() WHERE id=$1`, id, remote)
		if err != nil {
			return "", databaseError(err)
		}
	}
	return winner, databaseError(session.tx.Commit(ctx))
}

type UploadPart struct {
	Number   int32
	Transfer storage.SignedUpload
}

func (s *Store) GetUploadParts(ctx context.Context, scopeID, id uuid.UUID, numbers []int32) ([]UploadPart, error) {
	actor, err := s.authorize(ctx, scopeID, "scope", authz.ScopeWrite)
	if err != nil {
		return nil, err
	}
	return s.getUploadParts(ctx, scopeID, id, uploadAccess{actor: actor}, numbers)
}

func (s *Store) getUploadParts(ctx context.Context, scopeID, id uuid.UUID, access uploadAccess, numbers []int32) ([]UploadPart, error) {
	if len(numbers) < 1 || len(numbers) > 64 {
		return nil, apperr.New(apperr.Invalid, "VALIDATION", "1..64 parts required")
	}
	session, err := s.openSession(ctx, scopeID, true)
	if err != nil {
		return nil, err
	}
	defer session.tx.Rollback(ctx)
	upload, err := session.loadUpload(ctx, id, access)
	if err != nil {
		return nil, err
	}
	if err = upload.active(); err != nil {
		return nil, err
	}
	if upload.Transport != "multipart" || upload.parts != nil {
		return nil, uploadState("UPLOAD_NOT_TRANSFERABLE")
	}
	seen := make(map[int32]bool, len(numbers))
	result := make([]UploadPart, len(numbers))
	latest := time.Now()
	for i, number := range numbers {
		if seen[number] {
			return nil, apperr.New(apperr.Invalid, "VALIDATION", "duplicate part number")
		}
		seen[number] = true
		signed, err := s.signUpload(ctx, upload, &number, access.source != nil)
		if err != nil {
			return nil, err
		}
		if signed.ExpiresAt.After(latest) {
			latest = signed.ExpiresAt
		}
		result[i] = UploadPart{Number: number, Transfer: signed}
	}
	if err = session.recordCapability(ctx, id, latest, s.UploadTransferGrace); err != nil {
		return nil, err
	}
	return result, databaseError(session.tx.Commit(ctx))
}
