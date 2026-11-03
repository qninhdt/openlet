//go:build integration

package main

import (
	"context"
	"net"
	"os"
	"strings"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"openlet/apps/letfs/internal/config"
	"openlet/apps/letfs/internal/temporal"
	"openlet/apps/letfs/internal/testfixture"
	"openlet/packages/go/authz"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/rpc"
	sharedfixture "openlet/packages/go/testfixture"
)

func TestIntegrationCompositionChecksPolicyServesRealRPCAndDrains(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, address, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	tc, temporalAddress := testfixture.Temporal(t)
	contract, err := authz.LoadContract("../../../../packages/contracts/authz/schema.zed", "../../../../packages/contracts/authz/roles.json")
	require.NoError(t, err)
	input := map[string]string{
		"TEMPORAL_ADDRESS": temporalAddress, "TEMPORAL_NAMESPACE": "openlet",
		"DATABASE_URL": db.Config().ConnString(), "SPICEDB_ADDRESS": address, "SPICEDB_GRPC_PRESHARED_KEY": sharedfixture.SpiceDBKey,
		"GATEWAY_TOKEN": strings.Repeat("g", 32), "WORKSPACE_SERVICE_TOKEN": strings.Repeat("w", 32), "INGEST_SERVICE_TOKEN": strings.Repeat("i", 32), "ALLOW_PLAINTEXT_RPC": "true",
		"S3_ENDPOINT": "https://storage.invalid", "S3_BUCKET": "private", "S3_REGION": "auto", "S3_ACCESS_KEY_ID": "isolated-access", "S3_SECRET_ACCESS_KEY": "isolated-secret",
		"QDRANT_API_KEY":     "isolated-qdrant-token",
		"OPENROUTER_API_KEY": "isolated-provider-token",
	}
	cfg, err := config.Parse(func(key string) string { return input[key] })
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	err = serve(t.Context(), cfg, contract, listener, nil)
	require.ErrorContains(t, err, "authorization schema or role policy unavailable")
	require.NoError(t, listener.Close())
	policy, err := os.ReadFile("../../../../packages/contracts/authz/roles.json")
	require.NoError(t, err)
	expected, err := authz.ParseRolePolicy(policy)
	require.NoError(t, err)
	require.NoError(t, authz.InitializeRolePolicy(t.Context(), graph, expected))
	listener, err = net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan error, 1)
	go func() { done <- serve(ctx, cfg, contract, listener, nil) }()
	t.Cleanup(func() {
		cancel()
		select {
		case err := <-done:
			require.NoError(t, err)
		case <-time.After(35 * time.Second):
			t.Error("server drain deadline exceeded")
		}
		_ = listener.Close()
	})
	connection, err := rpc.Dial(listener.Addr().String(), cfg.WorkspaceToken, rpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	health := healthv1.NewHealthClient(connection)
	require.Eventually(t, func() bool {
		probe, cancel := context.WithTimeout(t.Context(), 200*time.Millisecond)
		defer cancel()
		state, err := health.Check(probe, &healthv1.HealthCheckRequest{})
		return err == nil && state.Status == healthv1.HealthCheckResponse_SERVING
	}, 10*time.Second, 50*time.Millisecond)
	_, err = health.Check(t.Context(), &healthv1.HealthCheckRequest{Service: "missing"})
	require.Equal(t, codes.NotFound, status.Code(err))
	ingestConnection, err := rpc.Dial(listener.Addr().String(), cfg.IngestToken, rpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, ingestConnection.Close()) })
	ingestHealth, err := healthv1.NewHealthClient(ingestConnection).Check(t.Context(), &healthv1.HealthCheckRequest{Service: letfsv1.IngestService_ServiceDesc.ServiceName})
	require.NoError(t, err)
	require.Equal(t, healthv1.HealthCheckResponse_SERVING, ingestHealth.Status)
	_, err = letfsv1.NewIngestServiceClient(ingestConnection).PrepareParse(t.Context(), &letfsv1.PrepareParseRequest{FileId: uuid.NewString(), Generation: 1})
	require.Equal(t, codes.NotFound, status.Code(err), "registered ingest handler checks stored job scope")
	_, err = letfsv1.NewIngestServiceClient(connection).PrepareParse(t.Context(), &letfsv1.PrepareParseRequest{})
	require.Equal(t, codes.PermissionDenied, status.Code(err), "owner credential cannot call private ingest")
	admin := letfsv1.NewStorageAdministrationServiceClient(connection)
	bucketID, fsID := uuid.Must(uuid.NewV7()).String(), uuid.Must(uuid.NewV7()).String()
	bucket, err := admin.CreateBucket(t.Context(), &letfsv1.CreateBucketRequest{BucketId: bucketID, IdempotencyKey: uuid.NewString(), LimitBytes: 1000})
	require.NoError(t, err)
	require.Equal(t, bucketID, bucket.Bucket.Id)
	fs, err := admin.CreateFilesystem(t.Context(), &letfsv1.CreateFilesystemRequest{FilesystemId: fsID, BucketId: bucketID, IdempotencyKey: uuid.NewString(), RootName: "files"})
	require.NoError(t, err)
	_, err = letfsv1.NewFilesystemServiceClient(connection).GetFilesystem(t.Context(), &letfsv1.GetFilesystemRequest{FilesystemId: fsID})
	require.Equal(t, codes.PermissionDenied, status.Code(err), "owner service has no user operation allowlist")
	browser, err := rpc.Dial(listener.Addr().String(), cfg.GatewayToken, rpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, browser.Close()) })
	actor := uuid.NewString()
	caller := metadata.AppendToOutgoingContext(t.Context(), "x-openlet-user-id", actor)
	_, err = letfsv1.NewStorageAdministrationServiceClient(browser).CreateBucket(caller, &letfsv1.CreateBucketRequest{BucketId: uuid.Must(uuid.NewV7()).String(), IdempotencyKey: uuid.NewString()})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	_, err = letfsv1.NewFilesystemServiceClient(browser).GetFilesystem(caller, &letfsv1.GetFilesystemRequest{FilesystemId: fsID})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	var updates []*v1.RelationshipUpdate
	touch := func(kind, id, relation, subjectKind, subject string) {
		updates = append(updates, &v1.RelationshipUpdate{Operation: v1.RelationshipUpdate_OPERATION_TOUCH, Relationship: &v1.Relationship{Resource: &v1.ObjectReference{ObjectType: kind, ObjectId: id}, Relation: relation, Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: subjectKind, ObjectId: subject}}}})
	}
	workspace, grant := uuid.NewString(), uuid.NewString()
	touch("filesystem", fsID, "workspace", "workspace", workspace)
	touch("workspace", workspace, "enabled", "user", "*")
	touch("workspace", workspace, "grant", "role_grant", grant)
	touch("role_grant", grant, "member", "user", actor)
	touch("role_grant", grant, "role", "role", "owner")
	_, err = graph.WriteRelationships(t.Context(), &v1.WriteRelationshipsRequest{Updates: updates})
	require.NoError(t, err)
	result, err := letfsv1.NewFilesystemServiceClient(browser).GetFilesystem(caller, &letfsv1.GetFilesystemRequest{FilesystemId: fsID})
	require.NoError(t, err)
	require.Equal(t, fs.Filesystem.RootId, result.Filesystem.RootId)
	_, err = letfsv1.NewFilesystemServiceClient(browser).CreateCopy(caller, &letfsv1.CreateCopyRequest{})
	require.Equal(t, codes.InvalidArgument, status.Code(err), "copy validates its contract before durable admission")
	files := letfsv1.NewFilesystemServiceClient(browser)
	paths := &letfsv1.PathContext{Mounts: []*letfsv1.Mount{{Path: "/drive", FilesystemId: fsID}}}
	source, err := files.CreateNode(caller, &letfsv1.CreateNodeRequest{FilesystemId: fsID, IdempotencyKey: uuid.NewString(), PathContext: paths,
		Input: &letfsv1.CreateNodeRequest_File{File: &letfsv1.InlineFileCreation{Parent: &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: fs.Filesystem.RootId}},
			Name: "source.bin", Content: []byte{0, 255, 1}, MediaType: "application/octet-stream"}}})
	require.NoError(t, err)
	copy, err := files.CreateCopy(caller, &letfsv1.CreateCopyRequest{FilesystemId: fsID, SourceId: source.Node.Id, ParentId: fs.Filesystem.RootId,
		Name: "copy.bin", Revision: &source.Node.Revision, IdempotencyKey: uuid.NewString(), PathContext: paths})
	require.NoError(t, err)
	job, stopJob := context.WithTimeout(t.Context(), 10*time.Second)
	defer stopJob()
	var copied temporal.CopyState
	require.NoError(t, tc.GetWorkflow(job, "copy/"+fsID+"/"+copy.Copy.Id, "").Get(job, &copied))
	require.Equal(t, "succeeded", copied.Status)
	progress, err := files.GetCopy(caller, &letfsv1.GetCopyRequest{FilesystemId: fsID, CopyId: copy.Copy.Id})
	require.NoError(t, err)
	require.EqualValues(t, 3, progress.Copy.CommittedBytes)
	_, err = graph.WriteRelationships(t.Context(), &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{{Operation: v1.RelationshipUpdate_OPERATION_DELETE, Relationship: expected[0]}}})
	require.NoError(t, err)
	state, err := health.Check(t.Context(), &healthv1.HealthCheckRequest{})
	require.NoError(t, err)
	require.Equal(t, healthv1.HealthCheckResponse_NOT_SERVING, state.Status)
	require.ErrorIs(t, authz.VerifyRolePolicy(t.Context(), graph, expected), authz.ErrPolicyMismatch, "readiness does not repair policy")
}
