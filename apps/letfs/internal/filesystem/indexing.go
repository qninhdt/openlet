package filesystem

import (
	"context"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"openlet/packages/go/rpc"
)

type VectorSpace struct {
	Model      string `json:"model"`
	Collection string `json:"collection"`
	Dimension  int32  `json:"dimension"`
}

func (v VectorSpace) Validate() error {
	if strings.TrimSpace(v.Model) == "" || v.Dimension < 1 || v.Dimension > 65536 || len(v.Collection) == 0 || len(v.Collection) > 100 {
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid vector space")
	}
	for _, c := range v.Collection {
		if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '_' || c == '-') {
			return rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid vector collection")
		}
	}
	return nil
}

func (p processingState) matchesSpace(v VectorSpace) bool {
	return p.model != nil && *p.model == v.Model && p.collection != nil && *p.collection == v.Collection && p.dimension != nil && *p.dimension == v.Dimension
}

func (g Generation) validate() error {
	if g.FileID == uuid.Nil || g.Generation <= 0 {
		return rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid processing generation")
	}
	return nil
}

type IndexPreparation struct {
	FilesystemID uuid.UUID
	Source       Generation
	Nodes        []ProcessingNode
	VectorSpace  VectorSpace
	Complete     bool
}

func (s *Store) PrepareIndex(ctx context.Context, source Generation) (IndexPreparation, error) {
	if err := source.validate(); err != nil {
		return IndexPreparation{}, err
	}
	if s.IndexSpace.Validate() != nil {
		return IndexPreparation{}, rpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "vector space configuration unavailable")
	}
	session, err := s.processingSession(ctx, source, false)
	if err != nil {
		return IndexPreparation{}, err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.enrichmentState(ctx, source)
	if err != nil {
		return IndexPreparation{}, err
	}
	if p.publication != "ready" {
		return IndexPreparation{}, uploadState("PUBLICATION_NOT_COMPLETE")
	}
	result := IndexPreparation{FilesystemID: session.fs, Source: source, VectorSpace: s.IndexSpace}
	if p.matchesSpace(s.IndexSpace) && p.indexStatus == "ready" && p.indexedGeneration != nil && *p.indexedGeneration == source.Generation {
		result.Complete = true
		return result, nil
	}
	if !p.matchesSpace(s.IndexSpace) {
		if err = session.enqueueIndexDeletion(ctx, []uuid.UUID{source.FileID}); err != nil {
			return result, err
		}
	}
	_, err = session.tx.Exec(ctx, `UPDATE files SET embedding_model=$2,vector_collection=$3,vector_dimension=$4,index_status='pending',indexed_generation=NULL,processing_error=NULL,processing_updated_at=now() WHERE node_id=$1`, source.FileID, s.IndexSpace.Model, s.IndexSpace.Collection, s.IndexSpace.Dimension)
	if err != nil {
		return result, databaseError(err)
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

func (s *Store) CompleteIndex(ctx context.Context, source Generation, space VectorSpace) error {
	if err := source.validate(); err != nil {
		return err
	}
	if err := space.Validate(); err != nil {
		return err
	}
	session, err := s.processingSession(ctx, source, false)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.enrichmentState(ctx, source)
	if err != nil {
		return err
	}
	if p.publication != "ready" {
		return uploadState("PUBLICATION_NOT_COMPLETE")
	}
	if !p.matchesSpace(space) || space != s.IndexSpace {
		return uploadState("VECTOR_SPACE_CHANGED")
	}
	_, err = session.tx.Exec(ctx, `UPDATE files SET indexed_generation=desired_generation,index_status='ready',processing_error=NULL,processing_updated_at=now() WHERE node_id=$1`, source.FileID)
	if err != nil {
		return databaseError(err)
	}
	if err = session.completeProcessingReceipt(ctx, source); err != nil {
		return err
	}
	return databaseError(session.tx.Commit(ctx))
}

func (s *Store) FailIndex(ctx context.Context, source Generation, space VectorSpace, code string) error {
	if err := source.validate(); err != nil {
		return err
	}
	if err := space.Validate(); err != nil {
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
	p, err := session.enrichmentState(ctx, source)
	if err != nil {
		return err
	}
	if !p.matchesSpace(space) {
		return uploadState("VECTOR_SPACE_CHANGED")
	}
	_, err = session.tx.Exec(ctx, `UPDATE files SET index_status='failed',processing_error=$2,processing_updated_at=now() WHERE node_id=$1 AND index_status!='ready'`, source.FileID, code)
	if err != nil {
		return databaseError(err)
	}
	if err = session.completeProcessingReceipt(ctx, source); err != nil {
		return err
	}
	return databaseError(session.tx.Commit(ctx))
}

func (s *Store) ReconcileVectorSpace(ctx context.Context) error {
	if err := s.IndexSpace.Validate(); err != nil {
		return err
	}
	space := s.IndexSpace
	rows, err := s.DB.Query(ctx, `WITH RECURSIVE live AS (
 SELECT n.id,n.kind,0 AS depth FROM nodes n JOIN filesystems fs ON fs.root_id=n.id JOIN quota_buckets b ON b.id=fs.bucket_id WHERE fs.state='active' AND b.state='active'
 UNION ALL SELECT n.id,n.kind,l.depth+1 FROM nodes n JOIN live l ON n.parent_id=l.id WHERE l.kind='directory' AND l.depth<128)
 SELECT f.node_id,f.desired_generation FROM files f JOIN live l ON l.id=f.node_id WHERE f.publication_status='ready'
 AND (f.embedding_model,f.vector_collection,f.vector_dimension) IS DISTINCT FROM ($1::text,$2::text,$3::int) ORDER BY f.processing_updated_at,f.node_id LIMIT 16`, space.Model, space.Collection, space.Dimension)
	if err != nil {
		return databaseError(err)
	}
	sources, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (Generation, error) {
		var source Generation
		err := row.Scan(&source.FileID, &source.Generation)
		return source, err
	})
	if err != nil {
		return databaseError(err)
	}
	for _, source := range sources {
		if err := s.reconcileVectorSpace(ctx, source, space); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) reconcileVectorSpace(ctx context.Context, source Generation, space VectorSpace) error {
	session, err := s.processingSession(ctx, source, true)
	if err != nil {
		return err
	}
	defer session.tx.Rollback(ctx)
	p, err := session.currentProcessing(ctx, source)
	if err != nil {
		return err
	}
	if p.publication != "ready" || p.matchesSpace(space) {
		return nil
	}
	if _, err = session.processingSource(ctx, p); err != nil {
		switch status.Code(err) {
		case codes.InvalidArgument, codes.PermissionDenied, codes.NotFound, codes.AlreadyExists, codes.FailedPrecondition, codes.Aborted:
			return nil
		default:
			return err
		}
	}
	if err = session.enqueueIndexDeletion(ctx, []uuid.UUID{source.FileID}); err != nil {
		return err
	}
	_, err = session.tx.Exec(ctx, `UPDATE files SET embedding_model=$2,vector_collection=$3,vector_dimension=$4,index_status='pending',indexed_generation=NULL,processing_error=NULL,processing_updated_at=now() WHERE node_id=$1`, source.FileID, space.Model, space.Collection, space.Dimension)
	if err != nil {
		return databaseError(err)
	}
	return databaseError(session.tx.Commit(ctx))
}
