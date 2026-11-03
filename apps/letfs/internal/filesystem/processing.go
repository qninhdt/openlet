package filesystem

import (
	"context"
	"crypto/sha256"
	"encoding/hex"

	"github.com/google/uuid"
	"google.golang.org/grpc/codes"
	"openlet/apps/letfs/internal/storage"
	"openlet/packages/go/rpc"
)

type ProcessingAttempt struct {
	Source Generation `json:"source"`
	Number int32      `json:"number"`
	ID     uuid.UUID  `json:"attempt_id"`
}

func (a ProcessingAttempt) validate() error {
	if a.Source.FileID == uuid.Nil || a.Source.Generation <= 0 || a.Number < 1 || a.Number > 3 || a.ID == uuid.Nil {
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid processing attempt")
	}
	return nil
}

type ParsePreparation struct {
	SourceID      uuid.UUID
	Format        string
	SizeBytes     int64
	InlineContent []byte
	SignedURL     string
	Complete      bool
}

type processingState struct {
	id                                 uuid.UUID
	generation                         int64
	actor                              *uuid.UUID
	format, identity                   *string
	publication                        string
	accepted                           int32
	attempt                            *uuid.UUID
	key                                *string
	content                            []byte
	parseManifest, publicationManifest *string
	indexStatus                        string
	indexedGeneration                  *int64
	model, collection                  *string
	dimension                          *int32
}

func (s *Store) processingSession(ctx context.Context, source Generation, lifecycle bool) (*session, error) {
	var fs uuid.UUID
	if err := s.DB.QueryRow(ctx, `SELECT filesystem_id FROM nodes WHERE id=$1`, source.FileID).Scan(&fs); err != nil {
		return nil, databaseError(err)
	}
	if lifecycle {
		return s.lifecycleSession(ctx, fs)
	}
	return s.openSession(ctx, fs, true)
}

func (s *session) currentProcessing(ctx context.Context, source Generation) (processingState, error) {
	var p processingState
	err := s.tx.QueryRow(ctx, `SELECT f.node_id,f.desired_generation,f.processing_actor_id,f.processing_format,f.processing_source_identity,
 f.publication_status,f.accepted_attempt,f.accepted_attempt_id,f.object_key,f.inline_bytes,f.parse_manifest_hash,f.publication_manifest_hash,
 f.index_status,f.indexed_generation,f.embedding_model,f.vector_collection,f.vector_dimension
 FROM files f JOIN nodes n ON n.id=f.node_id WHERE f.node_id=$1 AND n.filesystem_id=$2 FOR UPDATE OF f`, source.FileID, s.fs).
		Scan(&p.id, &p.generation, &p.actor, &p.format, &p.identity, &p.publication, &p.accepted, &p.attempt, &p.key, &p.content, &p.parseManifest, &p.publicationManifest,
			&p.indexStatus, &p.indexedGeneration, &p.model, &p.collection, &p.dimension)
	if err != nil {
		return p, databaseError(err)
	}
	if p.generation != source.Generation {
		return p, uploadState("SOURCE_REPLACED")
	}
	if p.publication == "failed" || p.publication == "not_required" {
		return p, uploadState("PROCESSING_NOT_ACTIVE")
	}
	return p, nil
}

func (s *session) processingSource(ctx context.Context, p processingState) (Node, error) {
	node, err := s.resolveOne(ctx, []Mount{{Path: "/", FilesystemID: s.fs}}, Locator{NodeID: &p.id})
	if err != nil {
		return Node{}, err
	}
	if err = node.writable(); err != nil {
		return Node{}, err
	}
	var identity string
	switch {
	case p.key != nil && p.content == nil:
		identity = "object:" + *p.key
	case p.key == nil && p.content != nil:
		digest := sha256.Sum256(p.content)
		identity = "inline:" + hex.EncodeToString(digest[:])
	default:
		return Node{}, uploadState("INVALID_SOURCE_IDENTITY")
	}
	if p.identity == nil || *p.identity != identity {
		return Node{}, uploadState("SOURCE_REPLACED")
	}
	return node, nil
}

func (p processingState) checkAttempt(attempt ProcessingAttempt) error {
	if p.accepted != attempt.Number || p.attempt == nil || *p.attempt != attempt.ID {
		return uploadState("STALE_PROCESSING_ATTEMPT")
	}
	return nil
}

func (s *session) acceptProcessing(ctx context.Context, p processingState, attempt ProcessingAttempt, stage string) error {
	if err := attempt.validate(); err != nil {
		return err
	}
	if p.accepted > attempt.Number || p.accepted == attempt.Number && (p.attempt == nil || *p.attempt != attempt.ID) {
		return uploadState("STALE_PROCESSING_ATTEMPT")
	}
	if p.accepted < attempt.Number {
		if err := s.discardUploads(ctx, attempt.Source, &stage); err != nil {
			return err
		}
		_, err := s.tx.Exec(ctx, `UPDATE files SET accepted_attempt=$2,accepted_attempt_id=$3,processing_updated_at=now() WHERE node_id=$1`,
			attempt.Source.FileID, attempt.Number, attempt.ID)
		return databaseError(err)
	}
	return nil
}

// PrepareParse is pipeline-local; the Ingest transport owns service/job admission.
func (s *Store) PrepareParse(ctx context.Context, attempt ProcessingAttempt) (ParsePreparation, error) {
	if err := attempt.validate(); err != nil {
		return ParsePreparation{}, err
	}
	session, err := s.processingSession(ctx, attempt.Source, false)
	if err != nil {
		return ParsePreparation{}, err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.currentProcessing(ctx, attempt.Source)
	if err != nil {
		return ParsePreparation{}, err
	}
	node, err := session.processingSource(ctx, p)
	if err != nil {
		return ParsePreparation{}, err
	}
	if p.publication != "pending" {
		return ParsePreparation{SourceID: node.ID, Complete: true}, nil
	}
	if err = session.acceptProcessing(ctx, p, attempt, "parse"); err != nil {
		return ParsePreparation{}, err
	}
	result := ParsePreparation{SourceID: node.ID, Format: *p.format, SizeBytes: node.SizeBytes, InlineContent: p.content}
	if err = session.tx.Commit(ctx); err != nil {
		return ParsePreparation{}, databaseError(err)
	}
	if p.key != nil {
		if s.Storage == nil {
			return ParsePreparation{}, storageError(ctx, storage.ErrUnavailable)
		}
		result.SignedURL, err = s.Storage.ProcessorDownloadURL(ctx, *p.key, "source", s.DownloadLifetime)
		if err != nil {
			return ParsePreparation{}, storageError(ctx, err)
		}
	}
	return result, nil
}

func (s *session) failProcessing(ctx context.Context, source Generation, code string) error {
	if err := s.discardUploads(ctx, source, nil); err != nil {
		return err
	}
	_, err := s.tx.Exec(ctx, `UPDATE files SET publication_status=CASE WHEN publication_status='ready' THEN publication_status ELSE 'failed' END,
 index_status=CASE WHEN index_status='ready' THEN index_status ELSE 'failed' END,processing_error=$2,processing_updated_at=now() WHERE node_id=$1`, source.FileID, code)
	if err != nil {
		return databaseError(err)
	}
	return s.completeProcessingReceipt(ctx, source)
}

func (s *Store) AbortParse(ctx context.Context, attempt ProcessingAttempt, code string) error {
	if err := attempt.validate(); err != nil {
		return err
	}
	switch code {
	case "PROCESSING_FAILED", "PROCESSING_CANCELLED", "DOCUMENT_INVALID", "RESOURCE_LIMIT", "QUOTA_EXCEEDED":
	default:
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid processing failure code")
	}
	session, err := s.processingSession(ctx, attempt.Source, true)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.currentProcessing(ctx, attempt.Source)
	if err != nil {
		return err
	}
	if _, err = session.processingSource(ctx, p); err != nil {
		return err
	}
	if p.publication != "pending" {
		return nil
	}
	if err = p.checkAttempt(attempt); err != nil {
		return err
	}
	if err = session.failProcessing(ctx, attempt.Source, code); err != nil {
		return err
	}
	return databaseError(session.tx.Commit(ctx))
}
