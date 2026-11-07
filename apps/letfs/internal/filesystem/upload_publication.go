package filesystem

import (
	"context"
	"encoding/json"
	"errors"
	"slices"
	"strings"
	"unicode"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

func multipartEvidence(parts []storage.PartReceipt, expected int32) error {
	if len(parts) == 0 || len(parts) > 10000 || len(parts) != int(expected) {
		return apperr.New(apperr.Invalid, "VALIDATION", "incomplete multipart receipts")
	}
	for i, part := range parts {
		if part.Number != int32(i+1) || part.ETag == "" || len(part.ETag) > 1024 || strings.IndexFunc(part.ETag, unicode.IsControl) >= 0 {
			return apperr.New(apperr.Invalid, "VALIDATION", "invalid ordered multipart receipts")
		}
	}
	return nil
}

func (s *Store) CompleteUpload(ctx context.Context, scopeID, id uuid.UUID, parts []storage.PartReceipt) (UploadPublication, error) {
	actor, err := s.authorize(ctx, scopeID, "scope", authz.ScopeWrite)
	if err != nil {
		return UploadPublication{}, err
	}
	return s.completeUpload(ctx, scopeID, id, uploadAccess{actor: actor}, parts)
}

func (s *Store) completeUpload(ctx context.Context, scopeID, id uuid.UUID, access uploadAccess, parts []storage.PartReceipt) (UploadPublication, error) {
	session, err := s.openSession(ctx, scopeID, true)
	if err != nil {
		return UploadPublication{}, err
	}
	defer session.tx.Rollback(ctx)
	upload, err := session.loadUpload(ctx, id, access)
	if err != nil {
		return UploadPublication{}, err
	}
	var frozen []storage.PartReceipt
	if upload.parts != nil {
		if err = json.Unmarshal(upload.parts, &frozen); err != nil {
			return UploadPublication{}, uploadState("INVALID_UPLOAD_STATE")
		}
		if len(parts) > 0 && !slices.Equal(parts, frozen) {
			return UploadPublication{}, uploadState("IDEMPOTENCY_CONFLICT")
		}
	}
	if upload.Transport != "multipart" && len(parts) > 0 {
		return UploadPublication{}, apperr.New(apperr.Invalid, "VALIDATION", "only multipart accepts receipts")
	}
	if upload.State == "finalized" {
		if access.source != nil {
			return UploadPublication{}, nil
		}
		if upload.Publication == nil {
			return UploadPublication{}, uploadState("INVALID_UPLOAD_STATE")
		}
		return *upload.Publication, nil
	}
	if err = upload.active(); err != nil {
		return UploadPublication{}, err
	}
	if upload.Transport == "inline" && upload.content == nil {
		return UploadPublication{}, uploadState("UPLOAD_NOT_READY")
	}
	if upload.Transport != "inline" && (s.Storage == nil || upload.key == nil) {
		return UploadPublication{}, storageError(ctx, storage.ErrUnavailable)
	}
	if upload.Transport == "multipart" {
		if len(parts) > 0 {
			if err = multipartEvidence(parts, upload.PartCount()); err != nil {
				return UploadPublication{}, err
			}
			frozen = parts
			upload.parts, err = json.Marshal(parts)
			if err != nil {
				return UploadPublication{}, err
			}
			_, err = session.tx.Exec(ctx, `UPDATE uploads SET completion_parts=$2,updated_at=now() WHERE id=$1`, id, upload.parts)
			if err != nil {
				return UploadPublication{}, databaseError(err)
			}
		}
		if len(frozen) == 0 {
			return UploadPublication{}, apperr.New(apperr.Invalid, "VALIDATION", "multipart completion requires receipts")
		}
	}
	_, err = session.tx.Exec(ctx, `UPDATE uploads SET state='completing',updated_at=now() WHERE id=$1`, id)
	if err != nil {
		return UploadPublication{}, databaseError(err)
	}
	if err = session.tx.Commit(ctx); err != nil {
		return UploadPublication{}, databaseError(err)
	}
	if upload.Transport != "inline" {
		head, err := s.Storage.Head(ctx, *upload.key)
		if errors.Is(err, storage.ErrNotFound) && upload.Transport == "multipart" {
			if upload.multipartID == nil {
				return UploadPublication{}, uploadState("UPLOAD_NOT_READY")
			}
			completeErr := s.Storage.CompleteMultipart(ctx, *upload.key, *upload.multipartID, frozen)
			// The unique candidate may exist even if completion returned a timeout or NoSuchUpload.
			head, err = s.Storage.Head(ctx, *upload.key)
			if err != nil && completeErr != nil {
				return UploadPublication{}, storageError(ctx, completeErr)
			}
		}
		if errors.Is(err, storage.ErrNotFound) {
			return UploadPublication{}, uploadState("UPLOAD_NOT_READY")
		}
		if err != nil {
			return UploadPublication{}, storageError(ctx, err)
		}
		if head.Size != upload.SizeBytes {
			if err = s.abortUpload(ctx, scopeID, id, access); err != nil {
				return UploadPublication{}, err
			}
			return UploadPublication{}, uploadState("UPLOAD_EVIDENCE_MISMATCH")
		}
	}
	result, err := s.publishUpload(ctx, scopeID, id, access)
	switch apperr.KindOf(err) {
	case apperr.Invalid, apperr.Missing, apperr.Exists, apperr.Conflict, apperr.Precondition, apperr.Forbidden, apperr.Limit:
		if cleanupErr := s.abortUpload(ctx, scopeID, id, access); cleanupErr != nil && errorReason(cleanupErr) != "UPLOAD_FINALIZED" {
			return UploadPublication{}, cleanupErr
		}
	}
	return result, err
}

func errorReason(err error) string {
	if fault, ok := apperr.As(err); ok {
		return fault.Reason
	}
	return ""
}

func (s *Store) publishUpload(ctx context.Context, scopeID, id uuid.UUID, access uploadAccess) (UploadPublication, error) {
	session, err := s.openSession(ctx, scopeID, true)
	if err != nil {
		return UploadPublication{}, err
	}
	defer session.tx.Rollback(ctx)
	upload, err := session.loadUpload(ctx, id, access)
	if err != nil {
		return UploadPublication{}, err
	}
	if upload.State == "finalized" {
		if access.source != nil {
			return UploadPublication{}, nil
		}
		if upload.Publication == nil {
			return UploadPublication{}, uploadState("INVALID_UPLOAD_STATE")
		}
		return *upload.Publication, nil
	}
	if err = upload.active(); err != nil {
		return UploadPublication{}, err
	}
	if access.source != nil {
		if upload.Transport == "inline" && upload.content == nil {
			return UploadPublication{}, uploadState("UPLOAD_NOT_READY")
		}
		result, err := json.Marshal(struct {
			ID        uuid.UUID `json:"id"`
			Status    string    `json:"status"`
			SizeBytes int64     `json:"size_bytes,string"`
		}{id, "finalized", upload.SizeBytes})
		if err != nil {
			return UploadPublication{}, err
		}
		_, err = session.tx.Exec(ctx, `UPDATE uploads SET state='finalized',result=$2,updated_at=now() WHERE id=$1`, id, result)
		if err != nil {
			return UploadPublication{}, databaseError(err)
		}
		return UploadPublication{}, databaseError(session.tx.Commit(ctx))
	}
	var saved savedUpload
	if err = json.Unmarshal(upload.input, &saved); err != nil {
		return UploadPublication{}, uploadState("INVALID_UPLOAD_STATE")
	}
	old, parent, name, err := session.uploadTarget(ctx, saved)
	if err != nil {
		return UploadPublication{}, err
	}
	var oldSize int64
	if old != nil {
		oldSize = old.SizeBytes
	}
	if err = session.usage(ctx, upload.SizeBytes-oldSize); err != nil {
		return UploadPublication{}, err
	}
	var nodeID uuid.UUID
	if old != nil {
		nodeID = old.ID
		if err = session.invalidate(ctx, nodeID); err != nil {
			return UploadPublication{}, err
		}
		if err = session.queueObject(ctx, nodeID); err != nil {
			return UploadPublication{}, err
		}
		_, err = session.tx.Exec(ctx, `UPDATE nodes SET size_bytes=$2,revision=revision+1,updated_at=now() WHERE id=$1`, nodeID, upload.SizeBytes)
	} else {
		if err = session.addNodes(ctx, 1); err != nil {
			return UploadPublication{}, err
		}
		nodeID = uuid.Must(uuid.NewV7())
		_, err = session.tx.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,$4,'file',$5)`, nodeID, scopeID, parent, name, upload.SizeBytes)
		if err == nil {
			err = session.bump(ctx, parent)
		}
	}
	if err != nil {
		return UploadPublication{}, databaseError(err)
	}
	if upload.key == nil {
		return UploadPublication{}, uploadState("INVALID_UPLOAD_STATE")
	}
	_, err = session.tx.Exec(ctx, `INSERT INTO files(node_id,storage_kind,object_key,media_type) VALUES($1,'object',$2,$3)
 ON CONFLICT(node_id) DO UPDATE SET storage_kind='object',inline_bytes=NULL,object_key=excluded.object_key,media_type=excluded.media_type`, nodeID, *upload.key, saved.Input.MediaType)
	if err != nil {
		return UploadPublication{}, databaseError(err)
	}
	node, err := session.fetch(ctx, nodeID)
	if err != nil {
		return UploadPublication{}, err
	}
	if err = session.recordIntent(ctx, node); err != nil {
		return UploadPublication{}, err
	}
	result := UploadPublication{NodeID: nodeID, Status: "finalized", Revision: node.Revision}
	encoded, err := json.Marshal(result)
	if err != nil {
		return UploadPublication{}, err
	}
	if err = session.completeUploadReceipt(ctx, id); err != nil {
		return UploadPublication{}, err
	}
	_, err = session.tx.Exec(ctx, `UPDATE uploads SET state='finalized',result_node_id=$2,result=$3,inline_bytes=NULL,updated_at=now() WHERE id=$1`, id, nodeID, encoded)
	if err != nil {
		return UploadPublication{}, databaseError(err)
	}
	return result, databaseError(session.tx.Commit(ctx))
}

func (s *session) completeUploadReceipt(ctx context.Context, id uuid.UUID) error {
	_, err := s.tx.Exec(ctx, `UPDATE idempotency_keys SET expires_at=now()+interval '24 hours' WHERE operation='create-upload' AND result->>'id'=$1 AND expires_at IS NULL`, id.String())
	return databaseError(err)
}

func (s *session) queueCandidate(ctx context.Context, id uuid.UUID) error {
	_, err := s.tx.Exec(ctx, `INSERT INTO object_deletions(object_key,filesystem_id,ambiguous_write,eligible_at)
 SELECT candidate_key,$2,transfer_deadline IS NOT NULL,greatest(now()+interval '15 minutes',transfer_deadline) FROM uploads WHERE id=$1 AND candidate_key IS NOT NULL
 ON CONFLICT(object_key) DO UPDATE SET ambiguous_write=object_deletions.ambiguous_write OR excluded.ambiguous_write,eligible_at=greatest(object_deletions.eligible_at,excluded.eligible_at)`, id, s.filesystemID)
	return databaseError(err)
}

func (s *Store) AbortUpload(ctx context.Context, scopeID, id uuid.UUID) error {
	actor, err := s.authorize(ctx, scopeID, "scope", authz.ScopeWrite)
	if err != nil {
		return err
	}
	return s.abortUpload(ctx, scopeID, id, uploadAccess{actor: actor})
}

func (s *Store) abortUpload(ctx context.Context, scopeID, id uuid.UUID, access uploadAccess) error {
	session, err := s.lifecycleSession(ctx, scopeID)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	upload, err := session.loadUpload(ctx, id, access)
	if err != nil {
		return err
	}
	if upload.State == "finalized" {
		return uploadState("UPLOAD_FINALIZED")
	}
	_, err = session.tx.Exec(ctx, `UPDATE uploads SET state='aborted',inline_bytes=NULL,updated_at=now() WHERE id=$1`, id)
	if err != nil {
		return databaseError(err)
	}
	if err = session.queueCandidate(ctx, id); err != nil {
		return err
	}
	if err = session.completeUploadReceipt(ctx, id); err != nil {
		return err
	}
	if err = session.tx.Commit(ctx); err != nil {
		return databaseError(err)
	}
	if upload.multipartID != nil && upload.key != nil {
		return s.abortMultipart(ctx, id, *upload.key, *upload.multipartID)
	}
	return nil
}

func (s *Store) abortMultipart(ctx context.Context, id uuid.UUID, key, remote string) error {
	if s.Storage == nil {
		return storageError(ctx, storage.ErrUnavailable)
	}
	if err := s.Storage.AbortMultipart(ctx, key, remote); err != nil && !errors.Is(err, storage.ErrNotFound) {
		return storageError(ctx, err)
	}
	_, err := s.DB.Exec(ctx, `UPDATE uploads SET multipart_id=NULL,updated_at=now() WHERE id=$1 AND multipart_id=$2 AND state='aborted'`, id, remote)
	return databaseError(err)
}
