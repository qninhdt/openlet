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

type DeletionScheduler interface {
	StartDeletion(context.Context, DeletionInput) error
}

type Service struct {
	Store      *Store
	Processing ProcessingScheduler
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

func (s *Service) dispatchTextMutation(ctx context.Context, result TextMutationResult, err error) (TextMutationResult, error) {
	if err == nil && result.Stat.Node.Revision != result.BeforeRevision {
		s.dispatchProcessing(ctx, result.Stat.Node.ID)
	}
	return result, err
}

func (s *Service) WriteText(ctx context.Context, scope uuid.UUID, target TextTarget, content []byte) (TextMutationResult, error) {
	result, err := s.Store.WriteText(ctx, scope, target, content)
	return s.dispatchTextMutation(ctx, result, err)
}

func (s *Service) AppendText(ctx context.Context, scope uuid.UUID, target TextTarget, content []byte) (TextMutationResult, error) {
	result, err := s.Store.AppendText(ctx, scope, target, content)
	return s.dispatchTextMutation(ctx, result, err)
}

func (s *Service) PatchText(ctx context.Context, scope uuid.UUID, target TextTarget, patch TextPatch) (TextMutationResult, error) {
	result, err := s.Store.PatchText(ctx, scope, target, patch)
	return s.dispatchTextMutation(ctx, result, err)
}

func (s *Service) TruncateText(ctx context.Context, scope uuid.UUID, target TextTarget, length int64, noCreate bool) (TextMutationResult, error) {
	result, err := s.Store.TruncateText(ctx, scope, target, length, noCreate)
	return s.dispatchTextMutation(ctx, result, err)
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

func (s *Service) CreateCopy(ctx context.Context, scopeID, key uuid.UUID, input CreateCopy) (Node, error) {
	return s.Store.CopyNode(ctx, scopeID, key, input)
}

func (s *Service) CreateDirectories(ctx context.Context, scope uuid.UUID, parent Locator, components []string, parents bool) (Node, error) {
	return s.Store.CreateDirectories(ctx, scope, parent, components, parents)
}

func (s *Service) TrashNode(ctx context.Context, scopeID uuid.UUID, locator Locator, revision *int64, emptyDirectory bool) (TrashEntry, error) {
	return s.Store.TrashNode(ctx, scopeID, locator, revision, emptyDirectory)
}

func (s *Service) RestoreTrash(ctx context.Context, scopeID, id uuid.UUID, input RestoreTrash) (Node, error) {
	return s.Store.RestoreTrash(ctx, scopeID, id, input)
}

func (s *Service) PurgeTrash(ctx context.Context, scopeID, id uuid.UUID) error {
	entry, err := s.Store.PrepareTrashPurge(ctx, scopeID, id)
	if err != nil || entry == nil {
		return err
	}
	return s.Store.PurgeTrashData(ctx, DeletionInput{ScopeID: scopeID, EntryID: &id})
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
