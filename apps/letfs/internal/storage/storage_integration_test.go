//go:build integration

package storage

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	az "github.com/authzed/authzed-go/proto/authzed/api/v1"
	authzed "github.com/authzed/authzed-go/v1"
	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/option"
	"github.com/qdrant/go-client/qdrant"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/emptypb"
)

func TestStorageSQLInvariants(t *testing.T) {
	ctx := context.Background()
	dsn := os.Getenv("OPENLET_TEST_DATABASE_URL")
	if dsn == "" {
		t.Fatal("OPENLET_TEST_DATABASE_URL must point to the isolated migrated LetFS test database")
	}
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	workspace, storage, root := uuid.NewString(), uuid.NewString(), uuid.NewString()
	folder, text, source, blobID := uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString()
	blobKey := "workspaces/" + workspace + "/blobs/" + blobID + "/source"
	defer func() {
		_, _ = pool.Exec(ctx, `DELETE FROM workspace_storage WHERE workspace_id=$1`, workspace)
	}()

	tx, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for _, stmt := range []struct {
		sql  string
		args []any
	}{
		{`INSERT INTO workspace_storage(workspace_id,quota_bytes,used_bytes) VALUES($1,1000,5)`, []any{workspace}},
		{`INSERT INTO storages(id,workspace_id,name,visibility,root_node_id,allow_blob_files,allow_indexing) VALUES($1,$2,'Test','private',$3,true,true)`, []any{storage, workspace, root}},
		{`INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,NULL,'','directory'),($3,$2,$1,'docs','directory'),($4,$2,$3,'note.txt','file'),($5,$2,$1,'source.pdf','file')`, []any{root, storage, folder, text, source}},
		{`INSERT INTO blobs(id,workspace_id,object_key,size_bytes,media_type,checksum,source_name,processing_stage) VALUES($1,$2,$3,2,'application/pdf','AAAAAA==','source.pdf','queued')`, []any{blobID, workspace, blobKey}},
		{`INSERT INTO files(node_id,version,blob_id,text_content,size_bytes,media_type) VALUES($1,1,NULL,'a'||chr(13)||chr(10),3,'text/plain'),($2,1,$3,NULL,2,'application/pdf')`, []any{text, source, blobID}},
	} {
		if _, err = tx.Exec(ctx, stmt.sql, stmt.args...); err != nil {
			t.Fatal(err)
		}
	}
	if err = tx.Commit(ctx); err != nil {
		t.Fatal(err)
	}

	destination, destinationRoot := uuid.NewString(), uuid.NewString()
	if _, err = pool.Exec(ctx, `INSERT INTO storages(id,workspace_id,name,visibility,root_node_id,allow_blob_files,allow_indexing) VALUES($1,$2,'Text only','private',$3,false,false)`, destination, workspace, destinationRoot); err != nil {
		t.Fatal(err)
	}
	if _, err = pool.Exec(ctx, `INSERT INTO nodes(id,storage_id,name,kind) VALUES($1,$2,'','directory')`, destinationRoot, destination); err != nil {
		t.Fatal(err)
	}

	tx, err = pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = moveSubtree(ctx, tx, source, destination, destinationRoot, "source.pdf", false); status.Code(err) != codes.InvalidArgument {
		t.Fatalf("allowed blob move into text-only storage: %v", err)
	}
	_ = tx.Rollback(ctx)
	var unchanged string
	if err = pool.QueryRow(ctx, `SELECT storage_id FROM nodes WHERE id=$1`, source).Scan(&unchanged); err != nil || unchanged != storage {
		t.Fatalf("rolled-back move mutated storage: %q %v", unchanged, err)
	}

	byPath := &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/docs/note.txt"}}
	v, err := oneResolved(ctx, pool, workspace, storage, byPath, true, false)
	if err != nil || v.Node.Id != text || v.Text == nil || *v.Text != "a\r\n" {
		t.Fatalf("path resolve: %+v %v", v, err)
	}
	escaped := &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "../../outside"}, RootNodeId: &folder}
	if _, err = oneResolved(ctx, pool, workspace, storage, escaped, false, false); status.Code(err) != codes.NotFound {
		t.Fatalf("escaped path: %v", err)
	}
	batch, err := resolve(ctx, pool, workspace, storage, []*pb.NodeLocator{byPath, {Locator: &pb.NodeLocator_NodeId{NodeId: source}}}, false, false)
	if err != nil || len(batch) != 2 || batch[0].Node.Id != text || batch[1].Node.Id != source {
		t.Fatalf("batch order: %+v %v", batch, err)
	}

	tx, err = pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = tx.Exec(ctx, `UPDATE nodes SET parent_id=NULL WHERE id=$1`, folder); err != nil {
		t.Fatal(err)
	}
	if _, err = oneResolved(ctx, tx, workspace, storage, &pb.NodeLocator{Locator: &pb.NodeLocator_NodeId{NodeId: text}}, false, false); status.Code(err) != codes.NotFound {
		t.Fatalf("resolved trashed node: %v", err)
	}
	_ = tx.Rollback(ctx)

	s := &Server{DB: pool, Settings: Settings{
		MaxTextBytes: 1024, DownloadURLTTLSeconds: 60, IdempotencyRetentionSeconds: 60,
		Processing: struct {
			MaxArtifacts              int   `yaml:"max_artifacts"`
			MaxManifestTextBytes      int64 `yaml:"max_manifest_text_bytes"`
			MaxArtifactBlobBytes      int64 `yaml:"max_artifact_blob_bytes"`
			ParseTimeoutSeconds       int   `yaml:"parse_timeout_seconds"`
			EnrichIndexTimeoutSeconds int   `yaml:"enrich_index_timeout_seconds"`
		}{MaxArtifacts: 16, MaxManifestTextBytes: 4096},
	}, FileTypes: testFileTypes(t)}

	saveReq := &pb.SaveParsedArtifactsRequest{BlobId: blobID, Artifacts: []*pb.ParsedArtifactInput{
		{Path: "README.md", Kind: pb.NodeKind_NODE_KIND_FILE, MediaType: "text/markdown", TextContent: proto.String("hello"), Indexable: false},
		{Path: "01-a.md", Kind: pb.NodeKind_NODE_KIND_FILE, MediaType: "text/markdown", TextContent: proto.String("A"), Indexable: true},
		{Path: "02-b.md", Kind: pb.NodeKind_NODE_KIND_FILE, MediaType: "text/markdown", TextContent: proto.String("B"), Indexable: true},
		{Path: "section/README.md", Kind: pb.NodeKind_NODE_KIND_FILE, MediaType: "text/markdown", TextContent: proto.String("S"), Indexable: true},
	}}
	if out, err := s.SaveParsedArtifacts(ctx, saveReq); err != nil || out.Stage != "parsed" {
		t.Fatalf("save parsed: %+v %v", out, err)
	}
	if out, err := s.SaveParsedArtifacts(ctx, saveReq); err != nil || out.Stage != "parsed" {
		t.Fatalf("save parsed replay: %+v %v", out, err)
	}

	artifactByPath, err := oneResolved(ctx, pool, workspace, storage, &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/source.pdf/README.md"}}, true, false)
	if err != nil || !artifactByPath.Node.Readonly || artifactByPath.Text == nil || *artifactByPath.Text != "hello" {
		t.Fatalf("artifact path resolution: %+v %v", artifactByPath, err)
	}
	artifactByParam, err := oneResolved(ctx, pool, workspace, storage, &pb.NodeLocator{Locator: &pb.NodeLocator_NodeId{NodeId: source}, ArtifactPath: proto.String("01-a.md")}, true, false)
	if err != nil || !artifactByParam.Node.Readonly || artifactByParam.Text == nil || *artifactByParam.Text != "A" {
		t.Fatalf("artifact_path locator resolution: %+v %v", artifactByParam, err)
	}

	gotBlob, err := s.GetBlobArtifacts(ctx, &pb.BlobRequest{BlobId: blobID})
	if err != nil || gotBlob.Outcome.Stage != "parsed" || len(gotBlob.Artifacts) != 5 {
		t.Fatalf("get blob artifacts: %+v %v", gotBlob, err)
	}

	var used int64
	if err = pool.QueryRow(ctx, `SELECT used_bytes FROM workspace_storage WHERE workspace_id=$1`, workspace).Scan(&used); err != nil || used != 5 {
		t.Fatalf("artifacts charged quota: %d %v", used, err)
	}

	enriched := "enriched text"
	if out, err := s.SaveEnrichedArtifacts(ctx, &pb.SaveEnrichedArtifactsRequest{
		BlobId: blobID,
		Artifacts: []*pb.EnrichedArtifactInput{
			{ArtifactId: artifactByPath.Node.Id, TextContent: &enriched, Title: proto.String("Overview"), Description: proto.String("Summary")},
		},
	}); err != nil || out.Stage != "enriched" {
		t.Fatalf("save enriched: %+v %v", out, err)
	}
	if out, err := s.CompleteBlobIndex(ctx, &pb.BlobRequest{BlobId: blobID}); err != nil || out.Stage != "ready" {
		t.Fatalf("complete index: %+v %v", out, err)
	}
	if err := s.reportBlobFailure(ctx, ProcessBlobInput{BlobID: blobID, Attempt: 0}); err != nil {
		t.Fatalf("report failure after ready: %v", err)
	}
	var stageAfter string
	if err = pool.QueryRow(ctx, `SELECT processing_stage FROM blobs WHERE id=$1`, blobID).Scan(&stageAfter); err != nil || stageAfter != "ready" {
		t.Fatalf("failure after ready mutated stage: %q %v", stageAfter, err)
	}

	// Copy sharing blob_id must protect blob from orphan GC until last file deleted.
	copiedID := uuid.NewString()
	if _, err = pool.Exec(ctx, `WITH n AS(INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,$3,'source-copy.pdf','file') RETURNING id) INSERT INTO files(node_id,version,blob_id,size_bytes,media_type) SELECT id,1,$4,2,'application/pdf' FROM n`, copiedID, storage, root, blobID); err != nil {
		t.Fatal(err)
	}
	tx, err = pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = tx.Exec(ctx, `DELETE FROM nodes WHERE id=$1`, copiedID); err != nil {
		t.Fatal(err)
	}
	orphaned, err := markOrphanBlobs(ctx, tx, []string{blobID})
	if err != nil || len(orphaned) != 0 {
		t.Fatalf("shared blob marked orphan early: %v %v", orphaned, err)
	}
	_ = tx.Commit(ctx)

	caller := "user:" + uuid.NewString()
	key := uuid.NewString()
	defer pool.Exec(ctx, `DELETE FROM idempotency_keys WHERE caller=$1`, caller)
	tx, err = pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	response := &pb.Node{Id: text}
	duplicate, err := sdk.Claim(ctx, tx, caller, "test", key, &emptypb.Empty{}, new(pb.Node), s.ttl())
	if err != nil || duplicate {
		t.Fatalf("claim: %v %v", duplicate, err)
	}
	if err = sdk.Finish(ctx, tx, caller, "test", key, response); err != nil {
		t.Fatal(err)
	}
	if err = tx.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	tx, err = pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	replayed := new(pb.Node)
	duplicate, err = sdk.Claim(ctx, tx, caller, "test", key, &emptypb.Empty{}, replayed, s.ttl())
	if err != nil || !duplicate || replayed.Id != text {
		t.Fatalf("receipt: %+v %v %v", replayed, duplicate, err)
	}
	_ = tx.Rollback(ctx)
	replayed = new(pb.Node)
	if duplicate, err = sdk.Replay(ctx, pool, caller, "test", key, &emptypb.Empty{}, replayed); err != nil || !duplicate || replayed.Id != text {
		t.Fatalf("replay: %+v %v %v", replayed, duplicate, err)
	}
	if duplicate, err = sdk.Replay(ctx, pool, caller, "test", uuid.NewString(), &emptypb.Empty{}, new(pb.Node)); err != nil || duplicate {
		t.Fatalf("missing receipt: %v %v", duplicate, err)
	}

	t.Run("archive and upload transfers", func(t *testing.T) { testTransfers(t, s, workspace, storage, folder) })
	var logical int64
	if err = pool.QueryRow(ctx, `SELECT (SELECT used_bytes FROM workspace_storage WHERE workspace_id=$1),(SELECT coalesce(sum(size_bytes),0) FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.storage_id=$2)`, workspace, storage).Scan(&used, &logical); err != nil || used != logical {
		t.Fatalf("file quota used=%d logical=%d: %v", used, logical, err)
	}

	tx, err = pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	freed, deletedBlobs, err := deleteSubtree(ctx, tx, root)
	if err != nil {
		t.Fatal(err)
	}
	if err = s.quota(ctx, tx, workspace, -freed); err != nil {
		t.Fatal(err)
	}
	orphaned, err = markOrphanBlobs(ctx, tx, deletedBlobs)
	if err != nil || len(orphaned) != 1 || orphaned[0] != blobID {
		t.Fatalf("last ref deleted must orphan blob: %v %v", orphaned, err)
	}
	if err = tx.Commit(ctx); err != nil {
		t.Fatal(err)
	}
	var finalUsed int64
	if err = pool.QueryRow(ctx, `SELECT used_bytes FROM workspace_storage WHERE workspace_id=$1`, workspace).Scan(&finalUsed); err != nil || finalUsed != 0 {
		t.Fatalf("expected 0 used bytes after subtree delete, got %d: %v", finalUsed, err)
	}
	_ = time.Second
}

type invariantGraphStub struct {
	az.UnimplementedPermissionsServiceServer
	denied  map[string]bool
	agentID string
}

func (g *invariantGraphStub) CheckPermission(_ context.Context, r *az.CheckPermissionRequest) (*az.CheckPermissionResponse, error) {
	perm := az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION
	if r.Resource != nil && g.denied[r.Resource.ObjectId] {
		perm = az.CheckPermissionResponse_PERMISSIONSHIP_NO_PERMISSION
	}
	return &az.CheckPermissionResponse{Permissionship: perm}, nil
}

func (g *invariantGraphStub) CheckBulkPermissions(_ context.Context, r *az.CheckBulkPermissionsRequest) (*az.CheckBulkPermissionsResponse, error) {
	pairs := make([]*az.CheckBulkPermissionsPair, len(r.Items))
	for i, item := range r.Items {
		perm := az.CheckPermissionResponse_PERMISSIONSHIP_HAS_PERMISSION
		if g.denied[item.Resource.ObjectId] && item.Permission == "read" {
			perm = az.CheckPermissionResponse_PERMISSIONSHIP_NO_PERMISSION
		}
		pairs[i] = &az.CheckBulkPermissionsPair{
			Request: item,
			Response: &az.CheckBulkPermissionsPair_Item{
				Item: &az.CheckBulkPermissionsResponseItem{Permissionship: perm},
			},
		}
	}
	return &az.CheckBulkPermissionsResponse{Pairs: pairs}, nil
}

func (g *invariantGraphStub) ReadRelationships(r *az.ReadRelationshipsRequest, stream grpc.ServerStreamingServer[az.ReadRelationshipsResponse]) error {
	return stream.Send(&az.ReadRelationshipsResponse{
		Relationship: &az.Relationship{
			Resource: &az.ObjectReference{ObjectType: "storage", ObjectId: r.RelationshipFilter.OptionalResourceId},
			Relation: "owner",
			Subject:  &az.SubjectReference{Object: &az.ObjectReference{ObjectType: "agent", ObjectId: g.agentID}},
		},
	})
}

type invariantQdrantStub struct {
	qdrant.UnimplementedPointsServer
	blobID string
}

func (q *invariantQdrantStub) Query(_ context.Context, _ *qdrant.QueryPoints) (*qdrant.QueryResponse, error) {
	dupPayload := func() map[string]*qdrant.Value {
		return map[string]*qdrant.Value{
			"blob_id":       qdrant.NewValueString(q.blobID),
			"artifact_path": qdrant.NewValueString("tables/001.csv"),
			"text":          qdrant.NewValueString("Europe Q1 growth"),
		}
	}
	return &qdrant.QueryResponse{
		Result: []*qdrant.ScoredPoint{
			{Id: qdrant.NewIDNum(1), Score: 0.9, Payload: dupPayload()},
			{Id: qdrant.NewIDNum(2), Score: 0.5, Payload: dupPayload()},
		},
	}, nil
}

func TestStorageRefactoredInvariants(t *testing.T) {
	ctx := context.Background()
	dsn := os.Getenv("OPENLET_TEST_DATABASE_URL")
	if dsn == "" {
		t.Fatal("OPENLET_TEST_DATABASE_URL is required")
	}
	pool, err := pgxpool.New(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer pool.Close()

	agentID := uuid.NewString()
	graphStub := &invariantGraphStub{denied: map[string]bool{}, agentID: agentID}
	graphLis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	graphSrv := grpc.NewServer()
	az.RegisterPermissionsServiceServer(graphSrv, graphStub)
	go graphSrv.Serve(graphLis)
	defer graphSrv.Stop()
	graphClient, err := authzed.NewClient(graphLis.Addr().String(), grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer graphClient.Close()

	var multipartCalls, copyCalls atomic.Int32
	s3Srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost && strings.Contains(r.URL.RawQuery, "uploads") {
			multipartCalls.Add(1)
			w.Header().Set("Content-Type", "application/xml")
			_, _ = io.WriteString(w, `<InitiateMultipartUploadResult><UploadId>mpu-1</UploadId></InitiateMultipartUploadResult>`)
			return
		}
		if r.Header.Get("x-amz-copy-source") != "" {
			copyCalls.Add(1)
			w.Header().Set("Content-Type", "application/xml")
			_, _ = io.WriteString(w, `<CopyObjectResult><ETag>"c1"</ETag></CopyObjectResult>`)
			return
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer s3Srv.Close()
	s3Client := s3.New(s3.Options{
		BaseEndpoint: aws.String(s3Srv.URL),
		Region:       "test",
		UsePathStyle: true,
		Credentials:  credentials.NewStaticCredentialsProvider("test", "test", ""),
	})

	ws := uuid.NewString()
	defer func() {
		_, _ = pool.Exec(ctx, `DELETE FROM storages WHERE workspace_id=$1`, ws)
		_, _ = pool.Exec(ctx, `DELETE FROM blobs WHERE workspace_id=$1`, ws)
		_, _ = pool.Exec(ctx, `DELETE FROM workspace_storage WHERE workspace_id=$1`, ws)
	}()
	if _, err = pool.Exec(ctx, `INSERT INTO workspace_storage(workspace_id,quota_bytes,used_bytes) VALUES($1,1000,900)`, ws); err != nil {
		t.Fatal(err)
	}

	// Seed 52 storages sorted by UUID where the first 50 are denied so ListStorages must cross batches.
	ids := make([]string, 52)
	for i := range ids {
		ids[i] = uuid.NewString()
	}
	sort.Strings(ids)
	for i := range ids {
		root := uuid.NewString()
		if _, err = pool.Exec(ctx, `INSERT INTO storages(id,workspace_id,name,visibility,root_node_id,allow_blob_files,allow_indexing) VALUES($1,$2,$3,'private',$4,true,true)`, ids[i], ws, fmt.Sprintf("s-%02d", i), root); err != nil {
			t.Fatal(err)
		}
		if _, err = pool.Exec(ctx, `INSERT INTO nodes(id,storage_id,name,kind) VALUES($1,$2,'','directory')`, root, ids[i]); err != nil {
			t.Fatal(err)
		}
		if i < 50 {
			graphStub.denied[ids[i]] = true
		}
	}

	s := &Server{
		DB:      pool,
		Graph:   graphClient,
		S3:      s3Client,
		Presign: s3.NewPresignClient(s3Client),
		Bucket:  "test",
		FileTypes: sdk.FileTypes{
			sdk.FileText: {"txt": "text/plain"},
			sdk.FileBlob: {"pdf": "application/pdf", "png": "image/png"},
		},
		Settings: Settings{
			MaxTextBytes:            1 << 20,
			MaxBlobBytes:            10 << 20,
			MultipartThresholdBytes: 100,
			MultipartPartBytes:      100,
			UploadURLTTLSeconds:     300,
		},
	}
	s.Settings.SemanticSearch.CandidateLimit = 10
	s.Settings.SemanticSearch.ResultLimit = 5
	actorCtx := metadata.NewIncomingContext(ctx, metadata.Pairs("x-openlet-agent-id", agentID))

	// 1. ListStorages skips 50 denied storages and populates AgentId owners.
	listedStorages, err := s.ListStorages(actorCtx, &pb.ListStoragesRequest{WorkspaceId: ws, PageSize: 1})
	if err != nil || len(listedStorages.Storages) != 1 || listedStorages.Storages[0].Id != ids[50] || listedStorages.NextPageToken != ids[50] {
		t.Fatalf("ListStorages gap pagination mismatch: resp=%+v err=%v", listedStorages, err)
	}
	if listedStorages.Storages[0].GetOwnership().GetAgentId() != agentID {
		t.Fatalf("expected agent owner %q, got %+v", agentID, listedStorages.Storages[0].Ownership)
	}

	// 2. CreateDirectories nested path creation + idempotency + file conflict.
	st := ids[50]
	deepDir, err := s.CreateDirectories(actorCtx, &pb.CreateDirectoriesRequest{
		WorkspaceId: ws, StorageId: st, Base: &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/"}}, Path: "a/b/c",
	})
	if err != nil {
		t.Fatalf("CreateDirectories failed: %v", err)
	}
	deepRepeat, err := s.CreateDirectories(actorCtx, &pb.CreateDirectoriesRequest{
		WorkspaceId: ws, StorageId: st, Base: &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/"}}, Path: "a/b/c",
	})
	if err != nil || deepRepeat.Id != deepDir.Id {
		t.Fatalf("CreateDirectories not idempotent: %+v vs %+v err=%v", deepRepeat, deepDir, err)
	}
	_, err = s.CreateNode(actorCtx, &pb.CreateNodeRequest{
		WorkspaceId: ws, StorageId: st, Parent: &pb.NodeLocator{Locator: &pb.NodeLocator_NodeId{NodeId: deepDir.Id}},
		Name: "note.txt", Content: &pb.CreateNodeRequest_Text{Text: &pb.TextContent{Content: "Match line1\nMatch line2\nother line3\n", MediaType: "text/plain"}},
		RequestId: uuid.NewString(),
	})
	if err != nil {
		t.Fatalf("CreateNode failed: %v", err)
	}
	if _, err = s.CreateDirectories(actorCtx, &pb.CreateDirectoriesRequest{
		WorkspaceId: ws, StorageId: st, Base: &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/"}}, Path: "a/b/c/note.txt/sub",
	}); status.Code(err) != codes.InvalidArgument {
		t.Fatalf("expected InvalidArgument on file conflict, got %v", err)
	}

	// 3. ListNodes artifact order + cursor & TextSearch CaseSensitive + LinesMode pagination.
	var rootNodeID string
	_ = pool.QueryRow(ctx, `SELECT root_node_id::text FROM storages WHERE id=$1`, st).Scan(&rootNodeID)
	blobID, fileNodeID := uuid.NewString(), uuid.NewString()
	_, err = pool.Exec(ctx, `INSERT INTO blobs(id,workspace_id,object_key,size_bytes,media_type,checksum,source_name,processing_stage) VALUES($1,$2,$3,5,'application/pdf','AAAAAA==','pack.pdf','ready')`,
		blobID, ws, "workspaces/"+ws+"/blobs/"+blobID+"/source")
	if err != nil {
		t.Fatal(err)
	}
	_, err = pool.Exec(ctx, `WITH n AS(INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,$3,'pack.pdf','file') RETURNING id)
		INSERT INTO files(node_id,version,blob_id,size_bytes,media_type) SELECT id,1,$4,5,'application/pdf' FROM n`,
		fileNodeID, st, rootNodeID, blobID)
	if err != nil {
		t.Fatal(err)
	}
	_, err = pool.Exec(ctx, `INSERT INTO blob_artifacts(id,blob_id,path,parent_path,kind,media_type,size_bytes,text_content,object_key,checksum,indexable) VALUES
		($1,$2,'tables','','directory','',0,NULL,NULL,'',false),
		($3,$2,'tables/001.csv','tables','file','text/csv',14,'Europe Q1 data',NULL,'',true),
		($4,$2,'tables/002.csv','tables','file','text/csv',14,'europe q2 data',NULL,'',true),
		($5,$2,'tables/003.csv','tables','file','text/csv',14,'Other Q3 data',NULL,'',true),
		($6,$2,'img.png','','file','image/png',500,NULL,$7,'AAAAAA==',false)`,
		uuid.NewString(), blobID, uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString(), "workspaces/"+ws+"/blobs/"+blobID+"/img.png")
	if err != nil {
		t.Fatal(err)
	}

	artPage1, err := s.ListNodes(actorCtx, &pb.ListNodesRequest{
		WorkspaceId: ws, StorageId: st, Parent: &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/pack.pdf/tables"}}, PageSize: 2,
	})
	if err != nil || len(artPage1.Nodes) != 2 || artPage1.Nodes[0].Name != "001.csv" || artPage1.Nodes[1].Name != "002.csv" || artPage1.NextPageToken == "" {
		t.Fatalf("ListNodes artifact page1 failed: %+v err=%v", artPage1, err)
	}
	artPage2, err := s.ListNodes(actorCtx, &pb.ListNodesRequest{
		WorkspaceId: ws, StorageId: st, Parent: &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/pack.pdf/tables"}}, PageSize: 2, PageToken: artPage1.NextPageToken,
	})
	if err != nil || len(artPage2.Nodes) != 1 || artPage2.Nodes[0].Name != "003.csv" || artPage2.NextPageToken != "" {
		t.Fatalf("ListNodes artifact page2 failed: %+v err=%v", artPage2, err)
	}

	tsCase, err := s.TextSearch(actorCtx, &pb.TextSearchRequest{
		WorkspaceId: ws, StorageId: st, Root: &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/pack.pdf"}}, Query: "Europe", CaseSensitive: true,
	})
	if err != nil || len(tsCase.Hits) != 1 || tsCase.Hits[0].ArtifactPath != "tables/001.csv" {
		t.Fatalf("TextSearch CaseSensitive mismatch: %+v err=%v", tsCase, err)
	}
	tsLines1, err := s.TextSearch(actorCtx, &pb.TextSearchRequest{
		WorkspaceId: ws, StorageId: st, Root: &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/a/b/c/note.txt"}}, Query: "Match", LinesMode: true, PageSize: 1,
	})
	if err != nil || len(tsLines1.Hits) != 1 || tsLines1.Hits[0].LineNumber != 1 || tsLines1.NextPageToken == "" {
		t.Fatalf("TextSearch LinesMode page1 failed: %+v err=%v", tsLines1, err)
	}
	tsLines2, err := s.TextSearch(actorCtx, &pb.TextSearchRequest{
		WorkspaceId: ws, StorageId: st, Root: &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/a/b/c/note.txt"}}, Query: "Match", LinesMode: true, PageSize: 1, PageToken: tsLines1.NextPageToken,
	})
	if err != nil || len(tsLines2.Hits) != 1 || tsLines2.Hits[0].LineNumber != 2 || tsLines2.NextPageToken != "" {
		t.Fatalf("TextSearch LinesMode page2 failed: %+v err=%v", tsLines2, err)
	}

	// 4. CreateUpload idempotent retry skips duplicate S3 CreateMultipartUpload.
	upReq := &pb.CreateUploadRequest{
		WorkspaceId: ws,
		StorageId:   st,
		Destination: &pb.CreateUploadRequest_Create{
			Create: &pb.UploadCreate{Parent: &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/"}}, Name: "big.pdf"},
		},
		SizeBytes: 256,
		Checksum:  "AAAAAA==",
		RequestId: uuid.NewString(),
	}
	u1, err := s.CreateUpload(actorCtx, upReq)
	if err != nil {
		t.Fatalf("CreateUpload 1 failed: %v", err)
	}
	u2, err := s.CreateUpload(actorCtx, upReq)
	if err != nil || u1.Id != u2.Id || multipartCalls.Load() != 1 {
		t.Fatalf("CreateUpload replay mismatch: u1=%+v u2=%+v s3=%d err=%v", u1, u2, multipartCalls.Load(), err)
	}

	// 5. CopyNode artifact exceeding remaining workspace quota rejects before S3 CopyObject.
	if _, err = s.CopyNode(actorCtx, &pb.TransferNodeRequest{
		WorkspaceId:          ws,
		StorageId:            st,
		Source:               &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/pack.pdf/img.png"}},
		DestinationStorageId: st,
		Parent:               &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/"}},
		Name:                 "copied.png",
		RequestId:            uuid.NewString(),
	}); status.Code(err) != codes.ResourceExhausted || copyCalls.Load() != 0 {
		t.Fatalf("expected ResourceExhausted without S3 CopyObject: code=%v copyCalls=%d", err, copyCalls.Load())
	}

	// 6. SemanticSearch emits telemetry without reranker and deduplicates duplicate chunks.
	embedSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":[{"index":0,"embedding":[0.1,0.2,0.3]}],"usage":{"prompt_tokens":3,"total_tokens":3}}`))
	}))
	defer embedSrv.Close()
	qLis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	qSrv := grpc.NewServer()
	qdrant.RegisterPointsServer(qSrv, &invariantQdrantStub{blobID: blobID})
	go qSrv.Serve(qLis)
	defer qSrv.Stop()
	_, qPortStr, _ := net.SplitHostPort(qLis.Addr().String())
	qPort, _ := strconv.Atoi(qPortStr)
	qClient, err := qdrant.NewClient(&qdrant.Config{Host: "127.0.0.1", Port: qPort, SkipCompatibilityCheck: true, PoolSize: 1})
	if err != nil {
		t.Fatal(err)
	}
	defer qClient.Close()
	s.Models = openai.NewClient(option.WithBaseURL(embedSrv.URL), option.WithAPIKey("fixture"), option.WithMaxRetries(0))
	s.EmbeddingModel = "embed"
	s.EmbeddingDimensions = 3
	s.Qdrant = qClient
	s.Collection = "chunks"

	recorder := tracetest.NewSpanRecorder()
	tp := trace.NewTracerProvider(trace.WithSpanProcessor(recorder))
	prevTP := otel.GetTracerProvider()
	otel.SetTracerProvider(tp)
	defer otel.SetTracerProvider(prevTP)
	defer tp.Shutdown(ctx)

	searchCtx, span := tp.Tracer("test").Start(actorCtx, "semantic")
	semResp, err := s.SemanticSearch(searchCtx, &pb.SemanticSearchRequest{
		WorkspaceId: ws, StorageId: st, Root: &pb.SemanticScope{Locator: &pb.SemanticScope_Path{Path: "/pack.pdf"}}, Query: "Europe",
	})
	span.End()
	if err != nil || len(semResp.Hits) != 1 {
		t.Fatalf("expected 1 deduplicated semantic hit, got %+v err=%v", semResp, err)
	}
	var semSpan trace.ReadOnlySpan
	for _, sp := range recorder.Ended() {
		if sp.Name() == "semantic" {
			semSpan = sp
		}
	}
	if semSpan == nil {
		t.Fatal("missing semantic span")
	}
	semAttrs := map[string]string{}
	for _, attr := range semSpan.Attributes() {
		semAttrs[string(attr.Key)] = attr.Value.Emit()
	}
	if !strings.Contains(semAttrs["langfuse.observation.output"], "Europe Q1 growth") || semAttrs["langfuse.observation.metadata.returned_count"] != "1" {
		t.Fatalf("missing semantic output telemetry without rerank: %v", semAttrs)
	}
}
