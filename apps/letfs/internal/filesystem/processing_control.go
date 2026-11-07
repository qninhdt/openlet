package filesystem

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/qninhdt/openlet/packages/go/authz"
)

func (g Generation) WorkflowID() string {
	return fmt.Sprintf("process-file/%s/%d", g.FileID, g.Generation)
}

type ProcessingStatus struct {
	FileID            uuid.UUID
	DesiredGeneration int64
	PublicationStatus string
	ErrorCode         *string
}

func (s *Store) GetProcessing(ctx context.Context, scopeID uuid.UUID, id uuid.UUID) (ProcessingStatus, error) {
	if _, err := s.authorize(ctx, scopeID, "scope", authz.ScopeReadMetadata); err != nil {
		return ProcessingStatus{}, err
	}
	session, err := s.openSession(ctx, scopeID, false)
	if err != nil {
		return ProcessingStatus{}, err
	}
	defer session.tx.Rollback(ctx)
	if _, err = session.resolveOne(ctx, Locator{NodeID: &id}); err != nil {
		return ProcessingStatus{}, err
	}
	var result ProcessingStatus
	err = session.tx.QueryRow(ctx, `SELECT node_id,desired_generation,publication_status,processing_error FROM files WHERE node_id=$1`, id).
		Scan(&result.FileID, &result.DesiredGeneration, &result.PublicationStatus, &result.ErrorCode)
	return result, databaseError(err)
}

type Reprocessing struct {
	FileID     uuid.UUID `json:"file_id"`
	Generation int64     `json:"generation,string"`
	WorkflowID string    `json:"workflow_id"`
}

func (s *Store) Reprocess(ctx context.Context, scopeID uuid.UUID, id, key uuid.UUID) (Reprocessing, error) {
	actor, err := s.authorize(ctx, scopeID, "scope", authz.ScopeWrite)
	if err != nil {
		return Reprocessing{}, err
	}
	if key == uuid.Nil {
		return Reprocessing{}, enrichmentValidation("request key required")
	}
	session, err := s.openSession(ctx, scopeID, true)
	if err != nil {
		return Reprocessing{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, Locator{NodeID: &id})
	if err != nil {
		return Reprocessing{}, err
	}
	if err = node.writable(); err != nil {
		return Reprocessing{}, err
	}
	format, _ := processingFormat(node.Name)
	if node.Kind != "file" || format == "" && session.allowBlobFiles {
		return Reprocessing{}, uploadState("PROCESSING_UNSUPPORTED")
	}
	var object *string
	var content []byte
	err = session.tx.QueryRow(ctx, `SELECT object_key,inline_bytes FROM files WHERE node_id=$1 FOR UPDATE`, id).Scan(&object, &content)
	if err != nil {
		return Reprocessing{}, databaseError(err)
	}
	var source string
	switch {
	case object != nil && content == nil:
		source = "object:" + *object
	case object == nil && content != nil:
		digest := sha256.Sum256(content)
		source = "inline:" + hex.EncodeToString(digest[:])
	default:
		return Reprocessing{}, uploadState("INVALID_SOURCE_IDENTITY")
	}
	hash, err := fingerprint(struct {
		FileID uuid.UUID `json:"file_id"`
		Source string    `json:"source"`
	}{id, source})
	if err != nil {
		return Reprocessing{}, err
	}
	scope := "scope/" + scopeID.String() + "/actor/" + actor.String()
	var savedHash string
	var saved []byte
	err = session.tx.QueryRow(ctx, `SELECT request_hash,result FROM idempotency_keys WHERE scope=$1 AND operation='process-file' AND request_key=$2 AND (expires_at IS NULL OR expires_at>now())`, scope, key.String()).Scan(&savedHash, &saved)
	if err == nil {
		if savedHash != hash {
			return Reprocessing{}, uploadState("IDEMPOTENCY_CONFLICT")
		}
		var result Reprocessing
		if json.Unmarshal(saved, &result) != nil {
			return Reprocessing{}, uploadState("INVALID_RECEIPT")
		}
		return result, nil
	}
	if !errors.Is(err, pgx.ErrNoRows) {
		return Reprocessing{}, databaseError(err)
	}
	if err = session.invalidate(ctx, id); err != nil {
		return Reprocessing{}, err
	}
	if err = session.recordIntent(ctx, node); err != nil {
		return Reprocessing{}, err
	}
	result := Reprocessing{FileID: id}
	if err = session.tx.QueryRow(ctx, `SELECT desired_generation FROM files WHERE node_id=$1`, id).Scan(&result.Generation); err != nil {
		return Reprocessing{}, databaseError(err)
	}
	result.WorkflowID = (Generation{FileID: id, Generation: result.Generation}).WorkflowID()
	data, err := json.Marshal(result)
	if err != nil {
		return Reprocessing{}, err
	}
	_, err = session.tx.Exec(ctx, `INSERT INTO idempotency_keys(scope,operation,request_key,request_hash,result) VALUES($1,'process-file',$2,$3,$4)
 ON CONFLICT(scope,operation,request_key) DO UPDATE SET request_hash=excluded.request_hash,result=excluded.result,expires_at=NULL WHERE idempotency_keys.expires_at<=now()`, scope, key.String(), hash, data)
	if err != nil {
		return Reprocessing{}, databaseError(err)
	}
	return result, databaseError(session.tx.Commit(ctx))
}

type ProcessingDispatch struct {
	Source        Generation
	Publication   string
	UpdatedAt     time.Time
	AllowIndexing bool
}

func scanDispatch(row pgx.Row) (ProcessingDispatch, error) {
	var result ProcessingDispatch
	err := row.Scan(&result.Source.FileID, &result.Source.Generation, &result.Publication, &result.UpdatedAt, &result.AllowIndexing)
	return result, databaseError(err)
}

func (s *Store) PendingProcessing(ctx context.Context, file uuid.UUID) (ProcessingDispatch, error) {
	return scanDispatch(s.DB.QueryRow(ctx, `SELECT f.node_id,f.desired_generation,f.publication_status,f.processing_updated_at,s.allow_indexing FROM files f JOIN nodes n ON n.id=f.node_id JOIN scopes s ON s.id=n.scope_id WHERE f.node_id=$1`, file))
}

func (s *Store) ProcessingCandidates(ctx context.Context) ([]ProcessingDispatch, error) {
	rows, err := s.DB.Query(ctx, `SELECT f.node_id,f.desired_generation,f.publication_status,f.processing_updated_at,scopeID.allow_indexing FROM files f JOIN nodes n ON n.id=f.node_id JOIN scopes scopeID ON scopeID.id=n.scope_id
 WHERE scopeID.state='active' AND (f.publication_status IN ('pending','parsed') OR f.publication_status='enriched' AND scopeID.allow_indexing) ORDER BY f.processing_updated_at,f.node_id LIMIT 16`)
	if err != nil {
		return nil, databaseError(err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (ProcessingDispatch, error) { return scanDispatch(row) })
}

// ReconcileProcessing rechecks the observed state after Temporal I/O before failing or redispatching it.
func (s *Store) ReconcileProcessing(ctx context.Context, candidate ProcessingDispatch, closed bool) (bool, error) {
	session, err := s.processingSession(ctx, candidate.Source, true)
	if err != nil {
		return false, err
	}
	defer session.tx.Rollback(ctx)
	current, err := scanDispatch(session.tx.QueryRow(ctx, `SELECT node_id,desired_generation,publication_status,processing_updated_at,$2::boolean FROM files WHERE node_id=$1 FOR UPDATE`, candidate.Source.FileID, session.allowIndexing))
	if err != nil {
		return false, err
	}
	if current.Source != candidate.Source || current.Publication != candidate.Publication || !current.UpdatedAt.Equal(candidate.UpdatedAt) {
		return false, nil
	}
	p, err := session.currentProcessing(ctx, candidate.Source)
	if err != nil {
		return false, err
	}
	_, err = session.processingSource(ctx, p)
	live := err == nil
	if err != nil {
		switch apperr.KindOf(err) {
		case apperr.Invalid, apperr.Forbidden, apperr.Missing, apperr.Exists, apperr.Precondition, apperr.Conflict:
		default:
			return false, err
		}
	}
	if !live || closed {
		code := "PROCESSING_FAILED"
		if !live {
			code = "SOURCE_TRASHED"
		}
		if err = session.failProcessing(ctx, candidate.Source, code); err != nil {
			return false, err
		}
	}
	return live && !closed, databaseError(session.tx.Commit(ctx))
}
