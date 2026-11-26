package chat

import (
	"context"
	"fmt"
	"path"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/chat/v1"
	letfspb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func conversationStorageIDs(convID string) (string, string, error) {
	id, err := uuid.Parse(convID)
	if err != nil {
		return "", "", invalid("invalid conversation_id")
	}
	return uuid.NewSHA1(id, []byte("storage")).String(), uuid.NewSHA1(id, []byte("root")).String(), nil
}

func (s *Server) ensureStorageInternal(ctx context.Context, workspaceID, convID string) (string, string, error) {
	storageID, rootID, err := conversationStorageIDs(convID)
	if err != nil {
		return "", "", err
	}

	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return "", "", err
	}
	defer tx.Rollback(ctx)

	var existingID *string
	var ready bool
	err = tx.QueryRow(ctx, `SELECT storage_id::text, storage_ready FROM conversations WHERE id=$1 AND workspace_id=$2 FOR UPDATE`, convID, workspaceID).Scan(&existingID, &ready)
	if err == pgx.ErrNoRows {
		return "", "", notFound("conversation")
	}
	if err != nil {
		return "", "", err
	}
	if ready && existingID != nil && *existingID != "" {
		return *existingID, rootID, tx.Commit(ctx)
	}
	if s.LetFSInternal == nil {
		return "", "", status.Error(codes.FailedPrecondition, "letfs internal client not configured")
	}
	_, err = s.LetFSInternal.CreateStorage(ctx, &letfspb.CreateStorageRequest{
		WorkspaceId: workspaceID,
		StorageId:   storageID,
		RootNodeId:  rootID,
		Owner: &letfspb.StorageOwnership{
			Owner: &letfspb.StorageOwnership_ConversationId{ConversationId: convID},
		},
		Name:           "Conversation · " + convID,
		Visibility:     letfspb.StorageVisibility_STORAGE_VISIBILITY_PRIVATE,
		AllowBlobFiles: true,
		AllowIndexing:  true,
	})
	if err != nil && status.Code(err) != codes.AlreadyExists {
		return "", "", err
	}
	if _, err = tx.Exec(ctx, `UPDATE conversations SET storage_id=$2, storage_ready=true WHERE id=$1`, convID, storageID); err != nil {
		return "", "", err
	}
	return storageID, rootID, tx.Commit(ctx)
}

func (s *Server) EnsureConversationStorage(ctx context.Context, r *pb.ConversationRequest) (*pb.EnsureConversationStorageResponse, error) {
	if _, err := s.check(ctx, "conversation", r.ConversationId, "participate"); err != nil {
		return nil, err
	}
	storageID, rootID, err := s.ensureStorageInternal(ctx, r.WorkspaceId, r.ConversationId)
	if err != nil {
		return nil, err
	}
	return &pb.EnsureConversationStorageResponse{
		StorageId:  storageID,
		RootNodeId: rootID,
	}, nil
}

func splitFilename(name string) (stem, ext string) {
	clean := path.Base(strings.TrimSpace(name))
	if clean == "" || clean == "." || clean == "/" {
		clean = "attachment"
	}
	ext = path.Ext(clean)
	stem = strings.TrimSuffix(clean, ext)
	if stem == "" {
		stem = clean
		ext = ""
	}
	return stem, ext
}

// copyForwardAttachments copies any attachment from an external storage into
// /attachments/<original_filename> in the destination conversation's private storage.
func (s *Server) copyForwardAttachments(ctx context.Context, caller sdk.Actor, workspaceID, convID string, atts []*pb.MessageAttachment) ([]*pb.MessageAttachment, error) {
	if len(atts) == 0 || s.LetFS == nil {
		return atts, nil
	}
	convStorageID, _, err := conversationStorageIDs(convID)
	if err != nil {
		return nil, err
	}
	needsCopy := false
	for _, a := range atts {
		if a.StorageId != convStorageID {
			needsCopy = true
			break
		}
	}
	if !needsCopy {
		return atts, nil
	}

	destStorageID, _, err := s.ensureStorageInternal(ctx, workspaceID, convID)
	if err != nil {
		return nil, err
	}
	callCtx := sdk.WithActor(ctx, caller)
	attDir, err := s.LetFS.CreateDirectories(callCtx, &letfspb.CreateDirectoriesRequest{
		WorkspaceId: workspaceID,
		StorageId:   destStorageID,
		Base:        &letfspb.NodeLocator{Locator: &letfspb.NodeLocator_Path{Path: "/"}},
		Path:        "attachments",
	})
	if err != nil {
		return nil, err
	}

	out := make([]*pb.MessageAttachment, len(atts))
	for i, a := range atts {
		if a.StorageId == destStorageID {
			out[i] = a
			continue
		}
		name := a.Name
		if name == "" {
			if st, err := s.LetFS.Stat(callCtx, &letfspb.NodeRequest{
				WorkspaceId: workspaceID,
				StorageId:   a.StorageId,
				Target:      &letfspb.NodeLocator{Locator: &letfspb.NodeLocator_NodeId{NodeId: a.NodeId}},
			}); err == nil && st.Name != "" {
				name = st.Name
			}
		}
		stem, ext := splitFilename(name)
		var copied *letfspb.Node
		for attempt := 1; attempt <= 50; attempt++ {
			candidate := stem + ext
			if attempt > 1 {
				candidate = fmt.Sprintf("%s-%d%s", stem, attempt, ext)
			}
			copied, err = s.LetFS.CopyNode(callCtx, &letfspb.TransferNodeRequest{
				WorkspaceId:          workspaceID,
				StorageId:            a.StorageId,
				Source:               &letfspb.NodeLocator{Locator: &letfspb.NodeLocator_NodeId{NodeId: a.NodeId}},
				DestinationStorageId: destStorageID,
				Parent:               &letfspb.NodeLocator{Locator: &letfspb.NodeLocator_NodeId{NodeId: attDir.Id}},
				Name:                 candidate,
				RequestId:            uuid.NewString(),
			})
			if err == nil {
				break
			}
			if status.Code(err) != codes.AlreadyExists {
				return nil, err
			}
		}
		if err != nil || copied == nil {
			return nil, fmt.Errorf("failed to copy attachment %q: %w", name, err)
		}
		kind := "file"
		if copied.Kind == letfspb.NodeKind_NODE_KIND_DIRECTORY {
			kind = "folder"
		}
		mediaType := a.MediaType
		sizeBytes := a.SizeBytes
		if copied.File != nil {
			if copied.File.MediaType != "" {
				mediaType = copied.File.MediaType
			}
			sizeBytes = copied.File.SizeBytes
		}
		out[i] = &pb.MessageAttachment{
			StorageId: destStorageID,
			NodeId:    copied.Id,
			Kind:      kind,
			Name:      copied.Name,
			MediaType: mediaType,
			SizeBytes: sizeBytes,
		}
	}
	return out, nil
}
