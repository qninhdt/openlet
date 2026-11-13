package storage

import (
	"context"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"go.temporal.io/sdk/activity"
	"google.golang.org/grpc/metadata"
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

func (s *Server) provisionInitialStorages(ctx context.Context, in sdk.InitialStoragesInput) error {
	ctx = consistentContext(ctx, in.ZedToken)
	if _, err := s.ProvisionWorkspaceStorage(ctx, &pb.ProvisionWorkspaceStorageRequest{WorkspaceId: in.WorkspaceID, QuotaBytes: in.Quota}); err != nil {
		return err
	}
	if _, err := s.CreateStorage(ctx, &pb.CreateStorageRequest{WorkspaceId: in.WorkspaceID, StorageId: in.SharedStorageID, RootNodeId: in.SharedRootID, Owner: &pb.StorageOwnership{Owner: &pb.StorageOwnership_WorkspaceId{WorkspaceId: in.WorkspaceID}}, Name: "Shared", Visibility: pb.StorageVisibility_STORAGE_VISIBILITY_PUBLIC, AllowBlobFiles: true, AllowIndexing: true}); err != nil {
		return err
	}
	_, err := s.CreateStorage(ctx, &pb.CreateStorageRequest{WorkspaceId: in.WorkspaceID, StorageId: in.PrivateStorageID, RootNodeId: in.PrivateRootID, Owner: &pb.StorageOwnership{Owner: &pb.StorageOwnership_UserId{UserId: in.UserID}}, Name: "Personal", Visibility: pb.StorageVisibility_STORAGE_VISIBILITY_PRIVATE, AllowBlobFiles: true, AllowIndexing: true})
	return err
}

func (s *Server) provisionMemberStorage(ctx context.Context, in sdk.MemberStorageInput) error {
	ctx = consistentContext(ctx, in.ZedToken)
	check, err := s.Graph.CheckPermission(ctx, &az.CheckPermissionRequest{Resource: sdk.Object("workspace", in.WorkspaceID), Permission: "participate", Subject: sdk.Subject(sdk.Actor{Type: "user", ID: in.UserID}), Consistency: sdk.Consistency(ctx)})
	if err != nil {
		return err
	}
	if check.Permissionship != az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION {
		return nil
	}
	request := &pb.ListStoragesRequest{WorkspaceId: in.WorkspaceID, OwnedOnly: true, PageSize: 100}
	for {
		rows, err := s.ListStorages(sdk.WithActor(ctx, sdk.Actor{Type: "user", ID: in.UserID}), request)
		if err != nil {
			return err
		}
		if len(rows.Storages) > 0 {
			return nil
		}
		if rows.NextPageToken == "" {
			break
		}
		request.PageToken = rows.NextPageToken
	}
	_, err = s.CreateStorage(ctx, &pb.CreateStorageRequest{WorkspaceId: in.WorkspaceID, StorageId: in.StorageID, RootNodeId: in.RootID, Owner: &pb.StorageOwnership{Owner: &pb.StorageOwnership_UserId{UserId: in.UserID}}, Name: "Personal", Visibility: pb.StorageVisibility_STORAGE_VISIBILITY_PRIVATE, AllowBlobFiles: true, AllowIndexing: true})
	return err
}

func (s *Server) deleteWorkspaceStorage(ctx context.Context, in sdk.WorkspaceCleanup) error {
	rows, err := s.DB.Query(ctx, `SELECT id FROM storages WHERE workspace_id=$1`, in.WorkspaceID)
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
	rows.Close()
	if err = rows.Err(); err != nil {
		return err
	}
	for _, id := range ids {
		if _, err = s.Graph.DeleteRelationships(ctx, &az.DeleteRelationshipsRequest{RelationshipFilter: &az.RelationshipFilter{ResourceType: "storage", OptionalResourceId: id}}); err != nil {
			return err
		}
		activity.RecordHeartbeat(ctx, id)
	}
	_, err = s.DB.Exec(ctx, `DELETE FROM workspace_storage WHERE workspace_id=$1`, in.WorkspaceID)
	return err
}
