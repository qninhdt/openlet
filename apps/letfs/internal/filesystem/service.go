package filesystem

import (
	"context"
	"log/slog"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/packages/go/apperr"
)

type ProcessingScheduler interface {
	StartProcessing(context.Context, ProcessingDispatch) error
}

type CopyScheduler interface {
	StartCopy(context.Context, CopyAdmission) error
	Copy(context.Context, uuid.UUID, uuid.UUID, uuid.UUID, bool) (CopyState, error)
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

func (s *Service) CreateNode(ctx context.Context, fs uuid.UUID, mounts []Mount, key uuid.UUID, input CreateNode) (Node, error) {
	node, err := s.Store.CreateNode(ctx, fs, mounts, key, input)
	if err == nil && node.Kind == "file" {
		s.dispatchProcessing(ctx, node.ID)
	}
	return node, err
}

func (s *Service) UpdateNode(ctx context.Context, fs uuid.UUID, mounts []Mount, input UpdateNode) (Node, error) {
	return s.Store.UpdateNode(ctx, fs, mounts, input)
}

func (s *Service) ReplaceContent(ctx context.Context, fs uuid.UUID, mounts []Mount, locator Locator, revision *int64, content []byte, mediaType string) (Node, error) {
	node, err := s.Store.ReplaceContent(ctx, fs, mounts, locator, revision, content, mediaType)
	if err == nil {
		s.dispatchProcessing(ctx, node.ID)
	}
	return node, err
}

func (s *Service) CreateUpload(ctx context.Context, fs uuid.UUID, mounts []Mount, key uuid.UUID, input UploadCreation) (Upload, error) {
	return s.Store.CreateUpload(ctx, fs, mounts, key, input)
}

func (s *Service) CompleteUpload(ctx context.Context, fs, upload uuid.UUID, parts []storage.PartReceipt) (UploadPublication, error) {
	publication, err := s.Store.CompleteUpload(ctx, fs, upload, parts)
	if err == nil {
		s.dispatchProcessing(ctx, publication.NodeID)
	}
	return publication, err
}

func (s *Service) AbortUpload(ctx context.Context, fs, upload uuid.UUID) error {
	return s.Store.AbortUpload(ctx, fs, upload)
}

func (s *Service) Reprocess(ctx context.Context, fs uuid.UUID, mounts []Mount, file, key uuid.UUID) (Reprocessing, error) {
	result, err := s.Store.Reprocess(ctx, fs, mounts, file, key)
	if err == nil {
		s.dispatchProcessing(ctx, result.FileID)
	}
	return result, err
}

func (s *Service) CreateCopy(ctx context.Context, fs uuid.UUID, mounts []Mount, key uuid.UUID, input CreateCopy) (CopyState, error) {
	admission, err := s.Store.AdmitCopy(ctx, fs, mounts, key, input)
	if err != nil {
		return CopyState{}, err
	}
	if s.Copies == nil {
		return CopyState{}, unavailable()
	}
	if err = s.Copies.StartCopy(ctx, admission); err != nil {
		slog.WarnContext(ctx, "copy dispatch deferred")
	}
	result := NewCopyState(admission)
	result.Status = "accepted"
	return result, nil
}

func (s *Service) GetCopy(ctx context.Context, fs, id uuid.UUID) (CopyState, error) {
	actor, inspectAny, err := s.Store.CopyReader(ctx, fs)
	if err != nil {
		return CopyState{}, err
	}
	if s.Copies == nil {
		return CopyState{}, unavailable()
	}
	return s.Copies.Copy(ctx, fs, id, actor, inspectAny)
}

func (s *Service) TrashNode(ctx context.Context, fs uuid.UUID, mounts []Mount, locator Locator, revision *int64) (TrashEntry, error) {
	return s.Store.TrashNode(ctx, fs, mounts, locator, revision)
}

func (s *Service) RestoreTrash(ctx context.Context, fs, id uuid.UUID) (Node, error) {
	return s.Store.RestoreTrash(ctx, fs, id)
}

func (s *Service) PurgeTrash(ctx context.Context, fs, id uuid.UUID) (*TrashEntry, error) {
	entry, err := s.Store.PrepareTrashPurge(ctx, fs, id)
	if err != nil || entry == nil {
		return entry, err
	}
	if s.Deletions == nil {
		return nil, unavailable()
	}
	if err = s.Deletions.StartDeletion(ctx, DeletionInput{FilesystemID: fs, EntryID: &id}); err != nil {
		slog.WarnContext(ctx, "trash purge dispatch deferred")
	}
	return entry, nil
}

type Storage struct {
	Bucket     Bucket
	Filesystem Filesystem
}

func (s *Service) CreateStorage(ctx context.Context, bucketKey uuid.UUID, bucket CreateBucket, filesystemKey uuid.UUID, fs CreateFilesystem) (Storage, error) {
	createdBucket, err := s.Store.CreateBucket(ctx, bucketKey, bucket)
	if err != nil {
		return Storage{}, err
	}
	createdFilesystem, err := s.Store.CreateFilesystem(ctx, filesystemKey, fs)
	return Storage{Bucket: createdBucket, Filesystem: createdFilesystem}, err
}

func (s *Service) DeleteFilesystem(ctx context.Context, id uuid.UUID) (bool, error) {
	if err := s.Store.PrepareFilesystemDeletion(ctx, id); err != nil {
		return false, err
	}
	completed, err := s.Store.FilesystemDeleted(ctx, id)
	if err != nil || completed {
		return completed, err
	}
	if s.Deletions == nil {
		return false, unavailable()
	}
	return false, s.Deletions.StartDeletion(ctx, DeletionInput{FilesystemID: id})
}
