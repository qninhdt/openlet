package filesystem

import (
	"context"
	"strings"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
)

type VectorSpace struct {
	Model      string `json:"model"`
	Collection string `json:"collection"`
	Dimension  int32  `json:"dimension"`
}

func (v VectorSpace) Validate() error {
	if strings.TrimSpace(v.Model) == "" || v.Dimension < 1 || v.Dimension > 65536 || len(v.Collection) == 0 || len(v.Collection) > 100 {
		return apperr.New(apperr.Invalid, "VALIDATION", "invalid vector space")
	}
	for _, c := range v.Collection {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '-') {
			return apperr.New(apperr.Invalid, "VALIDATION", "invalid vector collection")
		}
	}
	return nil
}

func (g Generation) validate() error {
	if g.FileID == uuid.Nil || g.Generation <= 0 {
		return apperr.New(apperr.Invalid, "VALIDATION", "invalid processing generation")
	}
	return nil
}

type IndexPreparation struct {
	FilesystemID uuid.UUID
	ScopeID      uuid.UUID
	Source       Generation
	Nodes        []ProcessingNode
	VectorSpace  VectorSpace
	Complete     bool
}

func (s *Store) PrepareIndex(ctx context.Context, source Generation) (IndexPreparation, error) {
	if err := source.validate(); err != nil {
		return IndexPreparation{}, err
	}
	session, err := s.processingSession(ctx, source, false)
	if err != nil {
		return IndexPreparation{}, err
	}
	defer session.tx.Rollback(ctx)
	if !session.allowIndexing {
		return IndexPreparation{}, apperr.New(apperr.Precondition, "INDEXING_DISABLED", "scope does not allow indexing")
	}
	if s.IndexSpace.Validate() != nil {
		return IndexPreparation{}, apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "vector space configuration unavailable")
	}
	p, err := session.enrichmentState(ctx, source)
	if err != nil {
		return IndexPreparation{}, err
	}
	if p.publication != "enriched" && p.publication != "ready" && p.publication != "index_failed" {
		return IndexPreparation{}, uploadState("PUBLICATION_NOT_COMPLETE")
	}
	result := IndexPreparation{FilesystemID: session.filesystemID, ScopeID: session.scopeID, Source: source, VectorSpace: s.IndexSpace}
	if p.publication == "ready" {
		result.Complete = true
		return result, nil
	}
	if p.publication == "index_failed" {
		if _, err = session.tx.Exec(ctx, `UPDATE files SET publication_status='enriched',processing_error=NULL,processing_updated_at=now() WHERE node_id=$1`, source.FileID); err != nil {
			return result, databaseError(err)
		}
	}
	result.Nodes, err = session.inventory(ctx, source.FileID, s.ProcessingMaxOutputs)
	if err != nil {
		return result, err
	}
	if err = session.tx.Commit(ctx); err != nil {
		return result, databaseError(err)
	}
	return result, s.signInventory(ctx, result.Nodes)
}

func (s *Store) CompleteIndex(ctx context.Context, source Generation) error {
	if err := source.validate(); err != nil {
		return err
	}
	session, err := s.processingSession(ctx, source, false)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	if !session.allowIndexing {
		return apperr.New(apperr.Precondition, "INDEXING_DISABLED", "scope does not allow indexing")
	}
	p, err := session.enrichmentState(ctx, source)
	if err != nil {
		return err
	}
	if p.publication != "enriched" && p.publication != "ready" && p.publication != "index_failed" {
		return uploadState("PUBLICATION_NOT_COMPLETE")
	}
	_, err = session.tx.Exec(ctx, `UPDATE files SET publication_status='ready',processing_error=NULL,processing_updated_at=now() WHERE node_id=$1`, source.FileID)
	if err != nil {
		return databaseError(err)
	}
	if err = session.completeProcessingReceipt(ctx, source); err != nil {
		return err
	}
	return databaseError(session.tx.Commit(ctx))
}

func (s *Store) FailIndex(ctx context.Context, source Generation, code string) error {
	if err := source.validate(); err != nil {
		return err
	}
	switch code {
	case "PROCESSING_FAILED", "DEPENDENCY_UNAVAILABLE", "RESOURCE_LIMIT":
	default:
		return enrichmentValidation("invalid indexing failure")
	}
	session, err := s.processingSession(ctx, source, true)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	if !session.allowIndexing {
		return apperr.New(apperr.Precondition, "INDEXING_DISABLED", "scope does not allow indexing")
	}
	if _, err = session.enrichmentState(ctx, source); err != nil {
		return err
	}
	_, err = session.tx.Exec(ctx, `UPDATE files SET publication_status='index_failed',processing_error=$2,processing_updated_at=now() WHERE node_id=$1 AND publication_status!='ready'`, source.FileID, code)
	if err != nil {
		return databaseError(err)
	}
	if err = session.completeProcessingReceipt(ctx, source); err != nil {
		return err
	}
	return databaseError(session.tx.Commit(ctx))
}
