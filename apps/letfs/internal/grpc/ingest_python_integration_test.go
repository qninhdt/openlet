//go:build integration

package grpc

import (
	"context"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"openlet/apps/letfs/internal/filesystem"
	"openlet/apps/letfs/internal/testfixture"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/identity"
	"openlet/packages/go/rpc"
)

func TestIntegrationPythonGeneratedClientPublishesParseViaGoRPC(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	store := &filesystem.Store{DB: db, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 100, ProcessingMaxOutputs: 10, ProcessingMaxOutputBytes: 100, MultipartThreshold: 5242880}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	bucket, fs, file := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := store.CreateBucket(owner, uuid.New(), filesystem.CreateBucket{ID: bucket, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: fs, BucketID: bucket, RootName: "root"})
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,filesystem_id,parent_id,name,kind) VALUES($1,$2,$3,'report.pdf','file')`, file, fs, created.RootID)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_actor_id,processing_format,processing_source_identity,publication_status,index_status) VALUES($1,'inline','',1,$2,'pdf','inline:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855','pending','pending')`, file, uuid.New())
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `UPDATE filesystems SET node_count=2 WHERE id=$1`, fs)
	require.NoError(t, err)
	const token = "isolated-python-ingest-token-1234567890"
	methods := []string{}
	for _, method := range letfsv1.IngestService_ServiceDesc.Methods {
		methods = append(methods, "/"+letfsv1.IngestService_ServiceDesc.ServiceName+"/"+method.MethodName)
	}
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{{Service: "ingest", Token: token, Methods: methods}})
	require.NoError(t, err)
	started := filepath.Join(t.TempDir(), "request-started")
	var prepareCalls, failedCalls, canceledCalls atomic.Int32
	transient := func(ctx context.Context, request any, info *grpcgo.UnaryServerInfo, handler grpcgo.UnaryHandler) (any, error) {
		if info.FullMethod == letfsv1.IngestService_PrepareParse_FullMethodName && prepareCalls.Add(1) <= 2 {
			return nil, status.Error(codes.Unavailable, "private dependency details")
		}
		if info.FullMethod == letfsv1.IngestService_FailIndex_FullMethodName {
			failedCalls.Add(1)
			return nil, status.Error(codes.Unavailable, "private backend details")
		}
		if info.FullMethod == letfsv1.IngestService_PrepareEnrichment_FullMethodName {
			if err := os.WriteFile(started, []byte("started"), 0o600); err != nil {
				return nil, err
			}
			<-ctx.Done()
			canceledCalls.Add(1)
			return nil, ctx.Err()
		}
		return handler(ctx, request)
	}
	server := grpcgo.NewServer(grpcgo.ChainUnaryInterceptor(authentication.Unary(), transient))
	letfsv1.RegisterIngestServiceServer(server, &Ingest{Store: store})
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	root, err := filepath.Abs("../../../..")
	require.NoError(t, err)
	ctx, cancel := context.WithTimeout(t.Context(), 60*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, "uv", "run", "--locked", "--package", "letfs-ingest", "python", "-c", pythonParseClient)
	command.Dir = root
	command.Env = append(os.Environ(), "OPENLET_TEST_RPC="+listener.Addr().String(), "OPENLET_TEST_INGEST_TOKEN="+token, "OPENLET_TEST_FILE="+file.String(), "OPENLET_TEST_STARTED="+started)
	output, err := command.CombinedOutput()
	require.NoError(t, err, "prepare=%d failure=%d canceled=%d: %s", prepareCalls.Load(), failedCalls.Load(), canceledCalls.Load(), output)
	require.Contains(t, string(output), "native-ingest-ok")
	require.EqualValues(t, 3, failedCalls.Load(), "transient exhaustion remains bounded")
	require.Eventually(t, func() bool { return canceledCalls.Load() == 1 }, time.Second, 10*time.Millisecond, "Python task cancellation reaches the actual server context")
	require.EqualValues(t, 4, prepareCalls.Load(), "two transient requests, actual prepare, then completed replay")
	var content []byte
	var publication string
	require.NoError(t, db.QueryRow(t.Context(), `SELECT f.inline_bytes FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.parent_id=$1 AND n.name='README.md'`, file).Scan(&content))
	require.Equal(t, []byte("# Report\n"), content)
	require.NoError(t, db.QueryRow(t.Context(), `SELECT publication_status FROM files WHERE node_id=$1`, file).Scan(&publication))
	require.Equal(t, "parsed", publication)
}

const pythonParseClient = `
import asyncio
import os
from uuid import uuid4
from pathlib import Path
from temporalio.exceptions import ApplicationError
from openlet_api.letfs.v1 import letfs_pb2 as pb
from letfs_ingest.ingest_rpc import IngestRPC

async def main():
    address = os.environ["OPENLET_TEST_RPC"]
    token = os.environ["OPENLET_TEST_INGEST_TOKEN"]
    file = os.environ["OPENLET_TEST_FILE"]
    request = pb.PrepareParseRequest(file_id=file, generation=1, attempt_number=1, attempt_id=str(uuid4()))
    async with IngestRPC(address, "wrong-token-but-valid-shape-123456789", allow_plaintext=True) as api:
        try:
            await api.call("PrepareParse", request)
            raise AssertionError("invalid credential was accepted")
        except ApplicationError as error:
            assert error.type == "UNAUTHENTICATED" and error.non_retryable
            assert "wrong-token" not in str(error)
    async with IngestRPC(address, token, allow_plaintext=True) as api:
        prepared = await api.call("PrepareParse", request)
        assert prepared.WhichOneof("result") == "input"
        assert prepared.input.WhichOneof("source") == "inline_content"
        assert prepared.input.inline_content == b""
        attempt = pb.ProcessingAttempt(file_id=file, generation=1, attempt_number=1, attempt_id=request.attempt_id)
        content = b"# Report\n"
        upload = await api.call("PrepareParseOutput", pb.PrepareParseOutputRequest(attempt=attempt, output=pb.OutputDescription(path="README.md", storage="inline", size_bytes=len(content))))
        scope = pb.OutputUploadScope(attempt=attempt, stage="parse", upload_id=upload.upload.id)
        stale = pb.OutputUploadScope(attempt=pb.ProcessingAttempt(file_id=file, generation=1, attempt_number=1, attempt_id=str(uuid4())), stage="parse", upload_id=upload.upload.id)
        try:
            await api.call("WriteOutputBytes", pb.WriteOutputBytesRequest(scope=stale, content=content))
            raise AssertionError("stale attempt was accepted")
        except ApplicationError as error:
            assert error.type == "STALE_PROCESSING_ATTEMPT" and error.non_retryable
        await api.call("WriteOutputBytes", pb.WriteOutputBytesRequest(scope=scope, content=content))
        finalized = await api.call("CompleteOutputUpload", pb.CompleteOutputUploadRequest(scope=scope))
        assert finalized.receipt.status == "finalized"
        result = await api.call("CompleteParse", pb.CompleteParseRequest(attempt=attempt, uploads=[upload.upload.id]))
        assert result.source_id == file
        replay = await api.call("PrepareParse", request)
        assert replay.WhichOneof("result") == "complete"
        try:
            await api.call("FailIndex", pb.FailIndexRequest())
            raise AssertionError("dependency exhaustion was accepted")
        except ApplicationError as error:
            assert error.type == "DEPENDENCY_UNAVAILABLE" and not error.non_retryable
            assert "private" not in str(error)
        task = asyncio.create_task(api.call("PrepareEnrichment", pb.PrepareEnrichmentRequest(attempt=attempt)))
        async with asyncio.timeout(3):
            while not Path(os.environ["OPENLET_TEST_STARTED"]).exists():
                if task.done():
                    await task
                    raise AssertionError("call completed before cancellation")
                await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
            raise AssertionError("cancelled RPC returned success")
        except asyncio.CancelledError:
            pass
    print("native-ingest-ok")

asyncio.run(main())
`
