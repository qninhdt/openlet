//go:build integration

package grpc

import (
	"context"
	"net"
	"testing"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"github.com/stretchr/testify/require"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
)

func TestIntegrationIngestParseOverAuthenticatedRPC(t *testing.T) {
	db := testfixture.Postgres(t, "../../../migrations/0001_initial.sql")
	store := &filesystem.Store{DB: db, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 100, ProcessingMaxOutputs: 10, ProcessingMaxOutputBytes: 100, MultipartThreshold: 5242880}
	store.IndexSpace = filesystem.VectorSpace{Model: "test-embedding", Collection: "files", Dimension: 8}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	bucket, fs, file := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := store.CreateBucket(owner, uuid.New(), filesystem.CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'report.pdf','file',0)`, file, fs, created.RootID)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_format,publication_status)
 VALUES($1,'inline','',1,'pdf','pending')`, file)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `UPDATE filesystems SET node_count=2 WHERE id=$1`, fs)
	require.NoError(t, err)
	methods := []string{}
	for _, method := range letfsv1.IngestService_ServiceDesc.Methods {
		methods = append(methods, "/"+letfsv1.IngestService_ServiceDesc.ServiceName+"/"+method.MethodName)
	}
	const ingestToken = "isolated-ingest-token-12345678901234567890"
	const gatewayToken = "isolated-ingest-gateway-12345678901234567890"
	// The gateway allowlist is deliberately broad to prove the handler also checks service authority.
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{{Service: "ingest", Token: ingestToken, Methods: methods}, {Service: "gateway", Token: gatewayToken, Gateway: true, Methods: methods}})
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	server := grpcgo.NewServer(grpcgo.UnaryInterceptor(authentication.Unary()))
	letfsv1.RegisterIngestServiceServer(server, &Ingest{Store: store})
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	conn, err := grpcgo.NewClient(listener.Addr().String(), grpcgo.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, conn.Close()) })
	client := letfsv1.NewIngestServiceClient(conn)
	ctx := metadata.NewOutgoingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+ingestToken))
	request := &letfsv1.PrepareParseRequest{FileId: file.String(), Generation: 1}
	_, err = client.PrepareParse(t.Context(), request)
	require.Equal(t, codes.Unauthenticated, status.Code(err))
	gateway := metadata.NewOutgoingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-user-id", uuid.NewString()))
	_, err = client.PrepareParse(gateway, request)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	prepared, err := client.PrepareParse(ctx, request)
	require.NoError(t, err)
	require.Equal(t, file.String(), prepared.GetInput().SourceId)
	require.Equal(t, "pdf", prepared.GetInput().Format)
	require.IsType(t, &letfsv1.ParseInput_InlineContent{}, prepared.GetInput().Source, "empty source still uses explicit inline oneof")
	require.EqualValues(t, 64, prepared.GetInput().InlineLimitBytes)
	require.EqualValues(t, 10, prepared.GetInput().MaxOutputs)
	attempt := &letfsv1.ProcessingGeneration{FileId: file.String(), Generation: 1}
	size := int64(3)
	output := &letfsv1.PrepareParseOutputRequest{Source: attempt, Output: &letfsv1.OutputDescription{Path: "page/content.md", Storage: "inline", SizeBytes: &size}}
	upload, err := client.PrepareParseOutput(ctx, output)
	require.NoError(t, err)
	scope := &letfsv1.OutputUploadScope{Source: attempt, Stage: "parse", UploadId: upload.Upload.Id}
	malformed := proto.Clone(output).(*letfsv1.PrepareParseOutputRequest)
	malformed.Output.SizeBytes = nil
	_, err = client.PrepareParseOutput(ctx, malformed)
	require.Equal(t, codes.InvalidArgument, status.Code(err))
	stale := proto.Clone(scope).(*letfsv1.OutputUploadScope)
	stale.Source.Generation++
	_, err = client.WriteOutputBytes(ctx, &letfsv1.WriteOutputBytesRequest{Scope: stale, Content: []byte{0, 255, 1}})
	require.Equal(t, codes.Aborted, status.Code(err))
	received, err := client.WriteOutputBytes(ctx, &letfsv1.WriteOutputBytesRequest{Scope: scope, Content: []byte{0, 255, 1}})
	require.NoError(t, err)
	require.Equal(t, "open", received.Receipt.Status)
	finalized, err := client.CompleteOutputUpload(ctx, &letfsv1.CompleteOutputUploadRequest{Scope: scope})
	require.NoError(t, err)
	require.Equal(t, "finalized", finalized.Receipt.Status)
	state, err := client.GetOutputUpload(ctx, &letfsv1.GetOutputUploadRequest{Scope: scope})
	require.NoError(t, err)
	require.Equal(t, finalized.Receipt.Id, state.Upload.GetReceipt().Id)
	require.Nil(t, state.Upload.GetPublication())

	readmeSize := int64(4)
	readme, err := client.PrepareParseOutput(ctx, &letfsv1.PrepareParseOutputRequest{Source: attempt, Output: &letfsv1.OutputDescription{Path: "README.md", Storage: "inline", SizeBytes: &readmeSize}})
	require.NoError(t, err)
	readmeScope := &letfsv1.OutputUploadScope{Source: attempt, Stage: "parse", UploadId: readme.Upload.Id}
	_, err = client.WriteOutputBytes(ctx, &letfsv1.WriteOutputBytesRequest{Scope: readmeScope, Content: []byte("root")})
	require.NoError(t, err)
	_, err = client.CompleteOutputUpload(ctx, &letfsv1.CompleteOutputUploadRequest{Scope: readmeScope})
	require.NoError(t, err)
	_, err = client.CompleteParse(ctx, &letfsv1.CompleteParseRequest{Source: attempt, Uploads: []string{scope.UploadId, readme.Upload.Id}, Directories: []string{"empty"}})
	require.NoError(t, err)
	complete, err := client.PrepareParse(ctx, request)
	require.NoError(t, err)
	require.Equal(t, file.String(), complete.GetComplete().SourceId)
	_, err = client.CompleteParse(ctx, &letfsv1.CompleteParseRequest{Source: attempt, Uploads: []string{scope.UploadId, readme.Upload.Id}, Directories: []string{"empty"}})
	require.NoError(t, err)
	_, err = client.CompleteParse(ctx, &letfsv1.CompleteParseRequest{Source: attempt, Uploads: []string{scope.UploadId}})
	require.NoError(t, err)
	_, err = client.GetOutputUpload(gateway, &letfsv1.GetOutputUploadRequest{Scope: scope})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	canceled, cancel := context.WithCancel(ctx)
	cancel()
	_, err = client.GetOutputUpload(canceled, &letfsv1.GetOutputUploadRequest{Scope: scope})
	require.Equal(t, codes.Canceled, status.Code(err))
	var content []byte
	require.NoError(t, db.QueryRow(t.Context(), `SELECT f.inline_bytes FROM uploads u JOIN files f ON f.node_id=u.result_node_id WHERE u.id=$1`, scope.UploadId).Scan(&content))
	require.Equal(t, []byte{0, 255, 1}, content)
	enriched, err := client.PrepareEnrichment(ctx, &letfsv1.PrepareEnrichmentRequest{Source: attempt})
	require.NoError(t, err)
	require.Len(t, enriched.GetInput().Nodes, 5)
	require.Equal(t, file.String(), enriched.GetInput().Nodes[0].Id)
	require.Nil(t, enriched.GetInput().Nodes[0].Content, "parsed original has no raw binary evidence")
	updates := make([]*letfsv1.EnrichmentUpdate, 0, 5)
	for _, node := range enriched.GetInput().Nodes {
		update := &letfsv1.EnrichmentUpdate{Id: node.Id, Path: node.Path}
		if node.Kind == "file" {
			update.Metadata = &letfsv1.SemanticMetadata{Title: "Report", Description: "Own text.", SemanticType: "document:report", Context: "Search evidence."}
			if node.Path != "" {
				body := []byte("rewritten " + node.Path)
				size := int64(len(body))
				replacement, err := client.PrepareEnrichmentOutput(ctx, &letfsv1.PrepareEnrichmentOutputRequest{Source: attempt, Output: &letfsv1.OutputDescription{Path: node.Path, Storage: "inline", SizeBytes: &size}})
				require.NoError(t, err)
				scope := &letfsv1.OutputUploadScope{Source: attempt, Stage: "enrichment", UploadId: replacement.Upload.Id}
				_, err = client.WriteOutputBytes(ctx, &letfsv1.WriteOutputBytesRequest{Scope: scope, Content: body})
				require.NoError(t, err)
				_, err = client.CompleteOutputUpload(ctx, &letfsv1.CompleteOutputUploadRequest{Scope: scope})
				require.NoError(t, err)
				update.UploadId = &replacement.Upload.Id
			}
		}
		updates = append(updates, update)
	}
	manifest := &letfsv1.CompleteEnrichmentRequest{Source: attempt, Nodes: updates}
	_, err = client.CompleteEnrichment(ctx, manifest)
	require.NoError(t, err)
	_, err = client.CompleteEnrichment(ctx, manifest)
	require.NoError(t, err)
	doneEnrichment, err := client.PrepareEnrichment(ctx, &letfsv1.PrepareEnrichmentRequest{Source: attempt})
	require.NoError(t, err)
	require.Equal(t, file.String(), doneEnrichment.GetComplete().SourceId)
	_, err = client.FailEnrichment(ctx, &letfsv1.FailEnrichmentRequest{Source: attempt, ErrorCode: "PROCESSING_FAILED"})
	require.NoError(t, err)
	var title, name string
	require.NoError(t, db.QueryRow(t.Context(), `SELECT f.inline_bytes,f.title,n.name FROM files f JOIN nodes n ON n.id=f.node_id WHERE f.node_id=$1`, file).Scan(&content, &title, &name))
	require.Empty(t, content)
	require.Equal(t, "Report", title)
	require.Equal(t, "report.pdf", name)
	source := &letfsv1.ProcessingGeneration{FileId: file.String(), Generation: 1}
	_, err = client.PrepareIndex(gateway, &letfsv1.PrepareIndexRequest{Source: source})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	index, err := client.PrepareIndex(ctx, &letfsv1.PrepareIndexRequest{Source: source})
	require.NoError(t, err)
	require.Equal(t, fs.String(), index.GetInput().FilesystemId)
	require.Equal(t, "test-embedding", index.GetInput().VectorSpace.Model)
	require.Len(t, index.GetInput().Nodes, 5)
	require.Nil(t, index.GetInput().Nodes[0].Content)
	_, err = client.CompleteIndex(ctx, &letfsv1.CompleteIndexRequest{Source: source})
	require.NoError(t, err)
	_, err = client.CompleteIndex(ctx, &letfsv1.CompleteIndexRequest{Source: source})
	require.NoError(t, err)
	_, err = client.FailIndex(ctx, &letfsv1.FailIndexRequest{Source: source, ErrorCode: "DEPENDENCY_UNAVAILABLE"})
	require.NoError(t, err)
	indexed, err := client.PrepareIndex(ctx, &letfsv1.PrepareIndexRequest{Source: source})
	require.NoError(t, err)
	require.Equal(t, file.String(), indexed.GetComplete().SourceId)
}
