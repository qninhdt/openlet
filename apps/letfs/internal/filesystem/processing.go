package filesystem

import (
	"context"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/storage"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
)

type ParsePreparation struct {
	SourceID      uuid.UUID
	Format        string
	SizeBytes     int64
	InlineContent []byte
	SignedURL     string
	Complete      bool
}

type processingState struct {
	id          uuid.UUID
	generation  int64
	format      *string
	publication string
	key         *string
	content     []byte
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
	err := s.tx.QueryRow(ctx, `SELECT f.node_id,f.desired_generation,f.processing_format,f.publication_status,f.object_key,f.inline_bytes
 FROM files f JOIN nodes n ON n.id=f.node_id WHERE f.node_id=$1 AND n.filesystem_id=$2 FOR UPDATE OF f`, source.FileID, s.fs).
		Scan(&p.id, &p.generation, &p.format, &p.publication, &p.key, &p.content)
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

	return node, nil
}

// PrepareParse is pipeline-local; the Ingest transport owns service/job admission.
func (s *Store) PrepareParse(ctx context.Context, source Generation) (ParsePreparation, error) {
	if err := source.validate(); err != nil {
		return ParsePreparation{}, err
	}
	session, err := s.processingSession(ctx, source, false)
	if err != nil {
		return ParsePreparation{}, err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.currentProcessing(ctx, source)
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
	if err := s.discardUploads(ctx, source); err != nil {
		return err
	}
	_, err := s.tx.Exec(ctx, `UPDATE files SET publication_status=CASE WHEN publication_status='ready' THEN 'ready' WHEN publication_status IN ('enriched','index_failed') THEN 'index_failed' ELSE 'failed' END,processing_error=$2,processing_updated_at=now() WHERE node_id=$1`, source.FileID, code)
	if err != nil {
		return databaseError(err)
	}
	return s.completeProcessingReceipt(ctx, source)
}

func (s *Store) AbortParse(ctx context.Context, source Generation, code string) error {
	if err := source.validate(); err != nil {
		return err
	}
	switch code {
	case "PROCESSING_FAILED", "PROCESSING_CANCELLED", "DOCUMENT_INVALID", "RESOURCE_LIMIT", "QUOTA_EXCEEDED":
	default:
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid processing failure code")
	}
	session, err := s.processingSession(ctx, source, true)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.currentProcessing(ctx, source)
	if err != nil {
		return err
	}
	if _, err = session.processingSource(ctx, p); err != nil {
		return err
	}
	if p.publication != "pending" {
		return nil
	}
	if err = session.failProcessing(ctx, source, code); err != nil {
		return err
	}
	return databaseError(session.tx.Commit(ctx))
}
