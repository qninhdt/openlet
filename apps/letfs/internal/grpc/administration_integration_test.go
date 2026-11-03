//go:build integration

package grpc

import (
	"context"
	"net"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"openlet/apps/letfs/internal/filesystem"
	"openlet/apps/letfs/internal/testfixture"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/rpc"
)

func TestIntegrationGenericAdministrationOverAuthenticatedRPC(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	const ownerToken = "isolated-storage-owner-token-123456789"
	const otherToken = "isolated-other-owner-token-12345678901"
	const gatewayToken = "isolated-public-gateway-token-12345678"
	methods := []string{letfsv1.StorageAdministrationService_CreateBucket_FullMethodName,
		letfsv1.StorageAdministrationService_CreateFilesystem_FullMethodName, letfsv1.StorageAdministrationService_FreezeBucket_FullMethodName,
		letfsv1.StorageAdministrationService_ListBucketFilesystems_FullMethodName, letfsv1.StorageAdministrationService_CompleteBucketDeletion_FullMethodName,
		letfsv1.StorageAdministrationService_ReleaseProvisioning_FullMethodName}
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{
		{Service: "workspace", Token: ownerToken, Methods: methods},
		{Service: "independent-resource", Token: otherToken, Methods: methods},
		{Service: "gateway", Token: gatewayToken, Gateway: true, Methods: methods},
	})
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	server := grpcgo.NewServer(grpcgo.UnaryInterceptor(authentication.Unary()))
	letfsv1.RegisterStorageAdministrationServiceServer(server, &Administration{Store: &filesystem.Store{DB: db, MaxNodes: 100}})
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	connection, err := grpcgo.NewClient(listener.Addr().String(), grpcgo.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	client := letfsv1.NewStorageAdministrationServiceClient(connection)
	deadline, cancel := context.WithTimeout(t.Context(), 10*time.Second)
	defer cancel()
	owner := metadata.NewOutgoingContext(deadline, metadata.Pairs("authorization", "Bearer "+ownerToken))
	other := metadata.NewOutgoingContext(deadline, metadata.Pairs("authorization", "Bearer "+otherToken))
	bucketID, fsID, key := uuid.Must(uuid.NewV7()).String(), uuid.Must(uuid.NewV7()).String(), uuid.NewString()
	request := &letfsv1.CreateBucketRequest{BucketId: bucketID, IdempotencyKey: key, LimitBytes: 9223372036854775807}
	bucket, err := client.CreateBucket(owner, request)
	require.NoError(t, err)
	require.Equal(t, request.LimitBytes, bucket.Bucket.LimitBytes)
	require.Equal(t, bucketID, bucket.Bucket.Id)
	replayed, err := client.CreateBucket(owner, request)
	require.NoError(t, err)
	require.Equal(t, bucket.Bucket.Id, replayed.Bucket.Id)
	fs, err := client.CreateFilesystem(owner, &letfsv1.CreateFilesystemRequest{FilesystemId: fsID, BucketId: bucketID, IdempotencyKey: uuid.NewString(), RootName: "documents"})
	require.NoError(t, err)
	require.Equal(t, fsID, fs.Filesystem.Id)
	require.NotEmpty(t, fs.Filesystem.RootId)
	_, err = client.ReleaseProvisioning(owner, &letfsv1.ReleaseProvisioningRequest{BucketId: bucketID, FilesystemId: fsID, RootId: fs.Filesystem.RootId})
	require.NoError(t, err)
	_, err = client.FreezeBucket(other, &letfsv1.FreezeBucketRequest{BucketId: bucketID, IdempotencyKey: uuid.NewString()})
	require.NoError(t, err)
	_, err = client.CreateBucket(deadline, request)
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	spoofed := metadata.NewOutgoingContext(deadline, metadata.Pairs("authorization", "Bearer "+otherToken, "x-openlet-service", "workspace"))
	_, err = client.FreezeBucket(spoofed, &letfsv1.FreezeBucketRequest{BucketId: bucketID, IdempotencyKey: uuid.NewString()})
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	public := metadata.NewOutgoingContext(deadline, metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-user-id", uuid.NewString()))
	_, err = client.CreateBucket(public, &letfsv1.CreateBucketRequest{BucketId: uuid.Must(uuid.NewV7()).String(), IdempotencyKey: uuid.NewString(), LimitBytes: 1})
	require.Equal(t, codes.PermissionDenied, status.Code(err), "domain boundary rejects a gateway even if an allowlist is misconfigured")
	var count int
	require.NoError(t, db.QueryRow(deadline, "SELECT count(*) FROM quota_buckets").Scan(&count))
	require.Equal(t, 1, count)
	_, err = client.FreezeBucket(owner, &letfsv1.FreezeBucketRequest{BucketId: bucketID, IdempotencyKey: uuid.NewString()})
	require.NoError(t, err)
	listed, err := client.ListBucketFilesystems(owner, &letfsv1.ListBucketFilesystemsRequest{BucketId: bucketID})
	require.NoError(t, err)
	require.Equal(t, []string{fsID}, listed.FilesystemIds)
}
