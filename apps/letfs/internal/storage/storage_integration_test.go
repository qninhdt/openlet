//go:build integration

package storage

import (
	"context"
	"os"
	"testing"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	sdk "github.com/qninhdt/openlet/packages/sdk-go"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
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
	workspace, storage, root, folder, text, source := uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString(), uuid.NewString()
	defer func() {
		_, err := pool.Exec(ctx, `DELETE FROM workspace_storage WHERE workspace_id=$1`, workspace)
		if err != nil {
			t.Error(err)
		}
	}()
	tx, err := pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	defer tx.Rollback(ctx)
	for _, statement := range []struct {
		sql  string
		args []any
	}{
		{`INSERT INTO workspace_storage(workspace_id,quota_bytes,used_bytes) VALUES($1,100,5)`, []any{workspace}},
		{`INSERT INTO storages(id,workspace_id,name,visibility,root_node_id,allow_blob_files,allow_indexing) VALUES($1,$2,'Test','private',$3,true,true)`, []any{storage, workspace, root}},
		{`INSERT INTO nodes(id,storage_id,parent_id,name,kind) VALUES($1,$2,NULL,'','directory'),($3,$2,$1,'docs','directory'),($4,$2,$3,'note.txt','file'),($5,$2,$1,'source.pdf','file')`, []any{root, storage, folder, text, source}},
		{`INSERT INTO files(node_id,version,size_bytes,media_type,text_content,object_key) VALUES($1,1,3,'text/plain','a'||chr(13)||chr(10),NULL),($2,1,2,'application/pdf',NULL,'objects/test-source')`, []any{text, source}},
		{`INSERT INTO processing(file_id,stage) VALUES($1,'pending')`, []any{source}},
	} {
		if _, err = tx.Exec(ctx, statement.sql, statement.args...); err != nil {
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
	if _, err = moveSubtree(ctx, tx, source, destination, destinationRoot, "moved.pdf", false); status.Code(err) != codes.InvalidArgument {
		t.Fatalf("blob moved into text-only storage: %v", err)
	}
	_ = tx.Rollback(ctx)
	var unchanged string
	if err = pool.QueryRow(ctx, `SELECT storage_id FROM nodes WHERE id=$1`, source).Scan(&unchanged); err != nil || unchanged != storage {
		t.Fatalf("rejected move changed storage: %s %v", unchanged, err)
	}
	byPath := &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/docs/note.txt"}}
	v, err := oneResolved(ctx, pool, workspace, storage, byPath, true, false)
	if err != nil || v.Node.Id != text || v.Text == nil || *v.Text != "a\r\n" {
		t.Fatalf("path resolution: %+v %v", v, err)
	}
	escaped := &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "../docs/note.txt"}, RootNodeId: &folder, CwdNodeId: &folder}
	if _, err = oneResolved(ctx, pool, workspace, storage, escaped, false, false); status.Code(err) != codes.NotFound {
		t.Fatalf("mount escaped: %v", err)
	}
	batch, err := resolve(ctx, pool, workspace, storage, []*pb.NodeLocator{byPath, {Locator: &pb.NodeLocator_NodeId{NodeId: source}}}, false, false)
	if err != nil || len(batch) != 2 || batch[0].Text != nil || batch[1].Node.File.Type != pb.FileType_FILE_TYPE_BLOB {
		t.Fatalf("batch header resolution: %+v %v", batch, err)
	}
	tx, err = pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = tx.Exec(ctx, `UPDATE nodes SET parent_id=NULL WHERE id=$1`, folder); err != nil {
		t.Fatal(err)
	}
	if _, err = oneResolved(ctx, tx, workspace, storage, &pb.NodeLocator{Locator: &pb.NodeLocator_NodeId{NodeId: text}}, false, false); status.Code(err) != codes.NotFound {
		t.Fatalf("detached descendant visible: %v", err)
	}
	_ = tx.Rollback(ctx)
	s := &Server{DB: pool, Settings: Settings{IdempotencyRetentionSeconds: 3600}}
	s.Settings.Processing.MaxArtifacts = 10
	s.Settings.Processing.MaxManifestTextBytes = 100
	request := &pb.CommitParseRequest{FileId: source, Version: 1, Artifacts: []*pb.Artifact{{Path: "README.md", Content: &pb.Artifact_Text{Text: &pb.TextContent{Content: "hello", MediaType: "text/markdown"}}}}}
	out, err := s.CommitParse(ctx, request)
	if err != nil || out.Stage != "parsed" {
		t.Fatalf("parse commit: %+v %v", out, err)
	}
	out, err = s.CommitParse(ctx, request)
	if err != nil || out.Stage != "parsed" {
		t.Fatalf("parse retry: %+v %v", out, err)
	}
	artifact, err := oneResolved(ctx, pool, workspace, storage, &pb.NodeLocator{Locator: &pb.NodeLocator_Path{Path: "/source.pdf/README.md"}}, false, false)
	if err != nil || !artifact.Node.Readonly {
		t.Fatalf("artifact writable: %+v %v", artifact, err)
	}
	enriched := "hello world"
	out, err = s.CommitEnrichment(ctx, &pb.CommitEnrichmentRequest{FileId: source, Version: 1, Artifacts: []*pb.EnrichedArtifact{{NodeId: artifact.Node.Id, TextContent: &enriched}}})
	if err != nil || out.Stage != "enriched" {
		t.Fatalf("enrichment: %+v %v", out, err)
	}
	if _, err = s.CompleteIndex(ctx, &pb.ProcessingRequest{FileId: source, Version: 1}); err != nil {
		t.Fatal(err)
	}
	out, err = s.FailProcessing(ctx, &pb.FailProcessingRequest{FileId: source, Version: 1, ErrorCode: "late"})
	if err != nil || out.Stage != "ready" {
		t.Fatalf("ready regressed: %+v %v", out, err)
	}
	out, err = s.CommitParse(ctx, &pb.CommitParseRequest{FileId: source, Version: 2})
	if err != nil || !out.Obsolete {
		t.Fatalf("stale version admitted: %+v %v", out, err)
	}
	var used int64
	if err = pool.QueryRow(ctx, `SELECT used_bytes FROM workspace_storage WHERE workspace_id=$1`, workspace).Scan(&used); err != nil || used != 16 {
		t.Fatalf("logical quota=%d error=%v", used, err)
	}
	tx, err = pool.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if err = s.quota(ctx, tx, workspace, 100); status.Code(err) != codes.ResourceExhausted {
		t.Fatalf("quota admitted: %v", err)
	}
	_ = tx.Rollback(ctx)
	caller := sdk.Actor{Type: "user", ID: uuid.NewString()}.String()
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
	duplicate, err = sdk.Replay(ctx, pool, caller, "test", key, &emptypb.Empty{}, replayed)
	if err != nil || !duplicate || replayed.Id != text {
		t.Fatalf("receipt preflight: %+v %v %v", replayed, duplicate, err)
	}
	if _, err = sdk.Replay(ctx, pool, caller, "test", key, &pb.Node{Id: source}, new(pb.Node)); status.Code(err) != codes.AlreadyExists {
		t.Fatalf("changed payload replayed: %v", err)
	}
	if duplicate, err = sdk.Replay(ctx, pool, caller, "test", uuid.NewString(), &emptypb.Empty{}, new(pb.Node)); err != nil || duplicate {
		t.Fatalf("missing receipt: %v %v", duplicate, err)
	}
}
