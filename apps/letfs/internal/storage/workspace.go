package storage

import (
	"context"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/qdrant/go-client/qdrant"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func consistentContext(ctx context.Context, token string) context.Context {
	if token == "" {
		return ctx
	}
	md, _ := metadata.FromIncomingContext(ctx)
	md = md.Copy()
	md.Set("x-openlet-zed-token", token)
	return metadata.NewIncomingContext(ctx, md)
}

func (s *Server) provisionInitialStorages(ctx context.Context, in sdk.InitialStoragesInput) (string, error) {
	ctx = consistentContext(ctx, in.ZedToken)
	if _, err := s.ProvisionWorkspaceStorage(ctx, &pb.ProvisionWorkspaceStorageRequest{WorkspaceId: in.WorkspaceID, QuotaBytes: in.Quota}); err != nil {
		return "", err
	}
	if _, _, err := s.createStorage(ctx, &pb.CreateStorageRequest{
		WorkspaceId: in.WorkspaceID, StorageId: in.SharedStorageID, RootNodeId: in.SharedRootID,
		Owner: &pb.StorageOwnership{Owner: &pb.StorageOwnership_WorkspaceId{WorkspaceId: in.WorkspaceID}},
		Name:  "Shared", Visibility: pb.StorageVisibility_STORAGE_VISIBILITY_PUBLIC, AllowBlobFiles: true, AllowIndexing: true,
	}); err != nil {
		return "", err
	}
	_, token, err := s.createStorage(ctx, &pb.CreateStorageRequest{
		WorkspaceId: in.WorkspaceID, StorageId: in.PrivateStorageID, RootNodeId: in.PrivateRootID,
		Owner: &pb.StorageOwnership{Owner: &pb.StorageOwnership_UserId{UserId: in.UserID}},
		Name:  "Personal", Visibility: pb.StorageVisibility_STORAGE_VISIBILITY_PRIVATE, AllowBlobFiles: true, AllowIndexing: true,
	})
	return token, err
}

func (s *Server) provisionMemberStorage(ctx context.Context, in sdk.MemberStorageInput) error {
	ctx = consistentContext(ctx, in.ZedToken)
	check, err := s.Graph.CheckPermission(ctx, &az.CheckPermissionRequest{
		Resource: sdk.Object("workspace", in.WorkspaceID), Permission: "participate",
		Subject: sdk.Subject(sdk.Actor{Type: "user", ID: in.UserID}), Consistency: sdk.Consistency(ctx),
	})
	if err != nil {
		return err
	}
	if check.Permissionship != az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION {
		return status.Error(codes.PermissionDenied, "member no longer belongs to workspace")
	}
	for request := ""; ; {
		rows, err := s.listStorages(ctx, &pb.ListStoragesRequest{WorkspaceId: in.WorkspaceID, Visibility: pb.StorageVisibility_STORAGE_VISIBILITY_PRIVATE.Enum(), PageSize: 100, PageToken: request}, sdk.Actor{Type: "user", ID: in.UserID})
		if err != nil {
			return err
		}
		for _, v := range rows.Storages {
			if owner := v.GetOwnership(); owner != nil && owner.GetUserId() == in.UserID {
				return nil
			}
		}
		if rows.NextPageToken == "" {
			break
		}
		request = rows.NextPageToken
	}
	_, _, err = s.createStorage(ctx, &pb.CreateStorageRequest{
		WorkspaceId: in.WorkspaceID, StorageId: in.StorageID, RootNodeId: in.RootID,
		Owner: &pb.StorageOwnership{Owner: &pb.StorageOwnership_UserId{UserId: in.UserID}},
		Name:  "Personal", Visibility: pb.StorageVisibility_STORAGE_VISIBILITY_PRIVATE, AllowBlobFiles: true, AllowIndexing: true,
	})
	return err
}

func (s *Server) deleteWorkspaceStorage(ctx context.Context, in sdk.WorkspaceCleanup) error {
	rows, err := s.DB.Query(ctx, `SELECT id::text FROM storages WHERE workspace_id=$1`, in.WorkspaceID)
	if err != nil {
		return err
	}
	var ids []string
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		ids = append(ids, id)
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, id := range ids {
		if _, err = s.Graph.DeleteRelationships(ctx, &az.DeleteRelationshipsRequest{
			RelationshipFilter: &az.RelationshipFilter{ResourceType: "storage", OptionalResourceId: id},
		}); err != nil {
			return err
		}
	}
	if s.Qdrant != nil {
		wait := true
		if _, err = s.Qdrant.Delete(ctx, &qdrant.DeletePoints{
			CollectionName: s.Collection,
			Points: qdrant.NewPointsSelectorFilter(&qdrant.Filter{
				Must: []*qdrant.Condition{qdrant.NewMatchKeyword("workspace_id", in.WorkspaceID)},
			}),
			Wait: &wait,
		}); err != nil {
			return err
		}
	}
	if err = s.deleteS3Prefix(ctx, "workspaces/"+in.WorkspaceID+"/"); err != nil {
		return err
	}
	_, err = s.DB.Exec(ctx, `DELETE FROM workspace_storage WHERE workspace_id=$1`, in.WorkspaceID)
	return err
}
