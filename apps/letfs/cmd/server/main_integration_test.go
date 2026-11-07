//go:build integration

package main

import (
	"context"
	"net"
	"strings"
	"testing"
	"time"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/config"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc/codes"
	healthv1 "google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func TestIntegrationCompositionChecksPolicyServesRealRPCAndDrains(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, address, graphServer := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	tc, temporalAddress := sharedfixture.Temporal(t)
	contract, err := authz.LoadContract("../../../../packages/contracts/authz/schema.zed")
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
	fsID, scopeID := uuid.Must(uuid.NewV7()).String(), uuid.Must(uuid.NewV7()).String()
	fs, err := admin.CreateFilesystem(t.Context(), &letfsv1.CreateFilesystemRequest{FilesystemId: fsID, IdempotencyKey: uuid.NewString(), LimitBytes: 1000})
	require.NoError(t, err)
	scopes, err := admin.CreateScopes(t.Context(), &letfsv1.CreateScopesRequest{FilesystemId: fsID, IdempotencyKey: uuid.NewString(), ScopeIds: []string{scopeID}})
	require.NoError(t, err)
	rootID := scopes.Scopes[0].RootId
	_, err = letfsv1.NewFilesystemServiceClient(connection).GetFilesystem(t.Context(), &letfsv1.GetFilesystemRequest{FilesystemId: fsID})
	require.Equal(t, codes.PermissionDenied, status.Code(err), "owner service has no user operation allowlist")
	browser, err := rpc.Dial(listener.Addr().String(), cfg.GatewayToken, rpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, browser.Close()) })
	actor := uuid.NewString()
	caller := metadata.AppendToOutgoingContext(t.Context(), "x-openlet-account-id", actor)
	_, err = letfsv1.NewStorageAdministrationServiceClient(browser).CreateFilesystem(caller, &letfsv1.CreateFilesystemRequest{FilesystemId: uuid.Must(uuid.NewV7()).String(), IdempotencyKey: uuid.NewString()})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	_, err = letfsv1.NewFilesystemServiceClient(browser).GetFilesystem(caller, &letfsv1.GetFilesystemRequest{FilesystemId: fsID})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	var updates []*v1.RelationshipUpdate
	touch := func(kind, id, relation, subjectKind, subject string) {
		updates = append(updates, &v1.RelationshipUpdate{Operation: v1.RelationshipUpdate_OPERATION_TOUCH, Relationship: &v1.Relationship{Resource: &v1.ObjectReference{ObjectType: kind, ObjectId: id}, Relation: relation, Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: subjectKind, ObjectId: subject}}}})
	}
	touch("filesystem", fsID, "reader", "account", actor)
	touch("scope", scopeID, "editor", "account", actor)
	_, err = graph.WriteRelationships(t.Context(), &v1.WriteRelationshipsRequest{Updates: updates})
	require.NoError(t, err)
	result, err := letfsv1.NewFilesystemServiceClient(browser).GetFilesystem(caller, &letfsv1.GetFilesystemRequest{FilesystemId: fsID})
	require.NoError(t, err)
	require.Equal(t, fs.Filesystem.Id, result.Filesystem.Id)
	_, err = letfsv1.NewFilesystemServiceClient(browser).CreateCopy(caller, &letfsv1.CreateCopyRequest{})
	require.Equal(t, codes.InvalidArgument, status.Code(err), "copy validates its contract before durable admission")
	files := letfsv1.NewFilesystemServiceClient(browser)
	source, err := files.CreateNode(caller, &letfsv1.CreateNodeRequest{FilesystemId: fsID, IdempotencyKey: uuid.NewString(), ScopeId: scopeID,
		Input: &letfsv1.CreateNodeRequest_File{File: &letfsv1.InlineFileCreation{Parent: &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: rootID}},
			Name: "source.bin", Content: []byte{0, 255, 1}, MediaType: "application/octet-stream"}}})
	require.NoError(t, err)
	copy, err := files.CreateCopy(caller, &letfsv1.CreateCopyRequest{FilesystemId: fsID, SourceId: source.Node.Id, ParentId: rootID,
		DestinationScopeId: scopeID, Name: "copy.bin", Revision: &source.Node.Revision, IdempotencyKey: uuid.NewString(), ScopeId: scopeID})
	require.NoError(t, err)
	job, stopJob := context.WithTimeout(t.Context(), 10*time.Second)
	defer stopJob()
	require.NoError(t, tc.GetWorkflow(job, "copy/"+fsID+"/"+copy.Copy.Id, "").Get(job, nil))
	require.NoError(t, graphServer.Stop(t.Context(), nil))
	state, err := health.Check(t.Context(), &healthv1.HealthCheckRequest{})
	require.NoError(t, err)
	require.Equal(t, healthv1.HealthCheckResponse_NOT_SERVING, state.Status)
}
