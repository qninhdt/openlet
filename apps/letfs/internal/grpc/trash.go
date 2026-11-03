package grpc

import (
	"context"
	"log/slog"

	"google.golang.org/grpc/codes"
	"google.golang.org/protobuf/types/known/timestamppb"
	"openlet/apps/letfs/internal/filesystem"
	"openlet/apps/letfs/internal/temporal"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/rpc"
)

func trashMessage(entry filesystem.TrashEntry) *letfsv1.TrashEntry {
	var parent *string
	if entry.ParentID != nil {
		value := entry.ParentID.String()
		parent = &value
	}
	return &letfsv1.TrashEntry{Id: entry.ID.String(), NodeId: entry.NodeID.String(), ParentId: parent, Name: entry.Name,
		ActorId: entry.ActorID.String(), Status: entry.Status, CreatedAt: timestamppb.New(entry.CreatedAt)}
}

func (s *Filesystem) TrashNode(ctx context.Context, input *letfsv1.TrashNodeRequest) (*letfsv1.TrashNodeResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	mounts, err := pathInput(input.GetPathContext())
	if err != nil {
		return nil, err
	}
	locator, err := locatorInput(input.GetLocator())
	if err != nil {
		return nil, err
	}
	entry, err := s.Store.TrashNode(ctx, fs, mounts, locator, input.Revision)
	if err != nil {
		return nil, err
	}
	return &letfsv1.TrashNodeResponse{Entry: trashMessage(entry)}, nil
}

func (s *Filesystem) GetTrash(ctx context.Context, input *letfsv1.GetTrashRequest) (*letfsv1.GetTrashResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetEntryId())
	if err != nil {
		return nil, err
	}
	entry, err := s.Store.GetTrash(ctx, fs, id)
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetTrashResponse{Entry: trashMessage(entry)}, nil
}

func (s *Filesystem) ListTrash(ctx context.Context, input *letfsv1.ListTrashRequest) (*letfsv1.ListTrashResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	page, err := s.Store.ListTrash(ctx, fs, input.Cursor, input.Limit)
	if err != nil {
		return nil, err
	}
	result := &letfsv1.ListTrashResponse{Items: make([]*letfsv1.TrashEntry, len(page.Items)), NextCursor: page.NextCursor}
	for i, entry := range page.Items {
		result.Items[i] = trashMessage(entry)
	}
	return result, nil
}

func (s *Filesystem) RestoreTrash(ctx context.Context, input *letfsv1.RestoreTrashRequest) (*letfsv1.RestoreTrashResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetEntryId())
	if err != nil {
		return nil, err
	}
	node, err := s.Store.RestoreTrash(ctx, fs, id)
	if err != nil {
		return nil, err
	}
	return &letfsv1.RestoreTrashResponse{Node: nodeMessage(node)}, nil
}

func (s *Filesystem) PurgeTrash(ctx context.Context, input *letfsv1.PurgeTrashRequest) (*letfsv1.PurgeTrashResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetEntryId())
	if err != nil {
		return nil, err
	}
	entry, err := s.Store.PrepareTrashPurge(ctx, fs, id)
	if err != nil {
		return nil, err
	}
	if entry == nil {
		return &letfsv1.PurgeTrashResponse{}, nil
	}
	if s.Jobs == nil {
		return nil, rpc.Fault(codes.Unavailable, "DEPENDENCY_UNAVAILABLE", "Temporal unavailable")
	}
	if err = s.Jobs.StartDeletion(ctx, temporal.DeletionInput{FilesystemID: fs, EntryID: &id}); err != nil {
		slog.WarnContext(ctx, "trash purge dispatch deferred")
	}
	return &letfsv1.PurgeTrashResponse{Entry: trashMessage(*entry)}, nil
}
