package filesystem

import (
	"context"
	"log/slog"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
	"github.com/qninhdt/openlet/packages/go/identity"
)

type ProcessingScheduler interface {
	StartProcessing(context.Context, ProcessingDispatch) error
}

type CopyScheduler interface {
	StartCopy(context.Context, CopyAdmission) error
}

type DeletionScheduler interface {
	StartDeletion(context.Context, DeletionInput) error
}

type Service struct {
	Store      *Store
	Processing ProcessingScheduler
	Copies     CopyScheduler
	Deletions  DeletionScheduler
}

func unavailable() error {
	return apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "Temporal unavailable")
}

func (s *Service) dispatchProcessing(ctx context.Context, file uuid.UUID) {
	if s.Processing == nil {
		return
	}
	dispatch, err := s.Store.PendingProcessing(ctx, file)
	if err == nil {
		err = s.Processing.StartProcessing(ctx, dispatch)
	}
	if err != nil {
		slog.WarnContext(ctx, "processing dispatch deferred")
	}
}

func (s *Service) CreateNode(ctx context.Context, scopeID uuid.UUID, key uuid.UUID, input CreateNode) (Node, error) {
	node, err := s.Store.CreateNode(ctx, scopeID, key, input)
	if err == nil && node.Kind == "file" {
		s.dispatchProcessing(ctx, node.ID)
	}
	return node, err
}

func (s *Service) UpdateNode(ctx context.Context, scopeID uuid.UUID, input UpdateNode) (Node, error) {
	return s.Store.UpdateNode(ctx, scopeID, input)
}

func (s *Service) ReplaceContent(ctx context.Context, scopeID uuid.UUID, locator Locator, revision *int64, content []byte, mediaType string) (Node, error) {
	node, err := s.Store.ReplaceContent(ctx, scopeID, locator, revision, content, mediaType)
	if err == nil {
		s.dispatchProcessing(ctx, node.ID)
	}
	return node, err
}

func (s *Service) CreateUpload(ctx context.Context, scopeID uuid.UUID, key uuid.UUID, input UploadCreation) (Upload, error) {
	return s.Store.CreateUpload(ctx, scopeID, key, input)
}

func (s *Service) CompleteUpload(ctx context.Context, scopeID, upload uuid.UUID, parts []storage.PartReceipt) (UploadPublication, error) {
	publication, err := s.Store.CompleteUpload(ctx, scopeID, upload, parts)
	if err == nil {
		s.dispatchProcessing(ctx, publication.NodeID)
	}
	return publication, err
}

func (s *Service) AbortUpload(ctx context.Context, scopeID, upload uuid.UUID) error {
	return s.Store.AbortUpload(ctx, scopeID, upload)
}

func (s *Service) Reprocess(ctx context.Context, scopeID uuid.UUID, file, key uuid.UUID) (Reprocessing, error) {
	result, err := s.Store.Reprocess(ctx, scopeID, file, key)
	if err == nil {
		s.dispatchProcessing(ctx, result.FileID)
	}
	return result, err
}

func (s *Service) CreateCopy(ctx context.Context, scopeID uuid.UUID, key uuid.UUID, input CreateCopy) (CopyResult, error) {
	admission, err := s.Store.AdmitCopy(ctx, scopeID, key, input)
	if err != nil {
		return CopyResult{}, err
	}
	if s.Copies == nil {
		return CopyResult{}, unavailable()
	}
	if err = s.Copies.StartCopy(ctx, admission); err != nil {
		return CopyResult{}, err
	}
	result := CopyResult{ID: admission.ID, DestinationRootID: admission.Root.Destination}
	return result, nil
}

func (s *Service) TrashNode(ctx context.Context, scopeID uuid.UUID, locator Locator, revision *int64) (TrashEntry, error) {
	return s.Store.TrashNode(ctx, scopeID, locator, revision)
}

func (s *Service) RestoreTrash(ctx context.Context, scopeID, id uuid.UUID) (Node, error) {
	return s.Store.RestoreTrash(ctx, scopeID, id)
}

func (s *Service) PurgeTrash(ctx context.Context, scopeID, id uuid.UUID) (*TrashEntry, error) {
	entry, err := s.Store.PrepareTrashPurge(ctx, scopeID, id)
	if err != nil || entry == nil {
		return entry, err
	}
	if s.Deletions == nil {
		return nil, unavailable()
	}
	if err = s.Deletions.StartDeletion(ctx, DeletionInput{ScopeID: scopeID, EntryID: &id}); err != nil {
		slog.WarnContext(ctx, "trash purge dispatch deferred")
	}
	return entry, nil
}

func (s *Service) DeleteFilesystem(ctx context.Context, id uuid.UUID) (bool, error) {
	principal, ok := identity.FromContext(ctx)
	if !ok {
		return false, apperr.New(apperr.Unauthenticated, "UNAUTHENTICATED", "verified actor required")
	}
	if principal.Gateway || principal.Service == "" {
		if _, err := s.Store.authorize(ctx, id, "filesystem", authz.FilesystemDelete); err != nil {
			return false, err
		}
	}
	var state string
	err := s.Store.DB.QueryRow(ctx, `SELECT state FROM filesystems WHERE id=$1`, id).Scan(&state)
	if errorReason(databaseError(err)) == "NOT_FOUND" {
		return true, nil
	}
	if err != nil {
		return false, databaseError(err)
	}
	if state == "deleted" {
		return true, nil
	}
	if s.Deletions == nil {
		return false, unavailable()
	}
	return false, s.Deletions.StartDeletion(ctx, DeletionInput{FilesystemID: id})
}
