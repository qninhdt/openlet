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
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"github.com/stretchr/testify/require"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func TestIntegrationPythonNativeClientPublishesParseViaGoRPC(t *testing.T) {
	db := testfixture.Postgres(t, "../../../migrations/0001_initial.sql")
	store := &filesystem.Store{DB: db, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 100, ProcessingMaxOutputs: 10, ProcessingMaxOutputBytes: 100, MultipartThreshold: 5242880}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	filesystemID, fs, file := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: filesystemID, LimitBytes: 1000})
	require.NoError(t, err)
	created, err := createTestScope(owner, store, uuid.New(), filesystemID, fs)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,scope_id,parent_id,name,kind) VALUES($1,$2,$3,'report.pdf','file')`, file, fs, created.RootID)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes,desired_generation,processing_format,publication_status) VALUES($1,'inline','',1,'pdf','pending')`, file)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `UPDATE filesystems SET node_count=2 WHERE id=$1`, filesystemID)
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
	root, err := filepath.Abs("../../../../..")
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
	require.NoError(t, db.QueryRow(t.Context(), `SELECT COALESCE(f.inline_bytes,convert_to(f.text_content,'UTF8')) FROM files f JOIN nodes n ON n.id=f.node_id WHERE n.parent_id=$1 AND n.name='README.md'`, file).Scan(&content))
	require.Equal(t, []byte("# Report\n"), content)
	require.NoError(t, db.QueryRow(t.Context(), `SELECT publication_status FROM files WHERE node_id=$1`, file).Scan(&publication))
	require.Equal(t, "parsed", publication)
}

const pythonParseClient = `
import asyncio
import os
from pathlib import Path
from openlet.clients.letfs import Generation, OutputDescription, OutputScope, ProcessingClient
from openlet.errors import AppError
from openlet.rpc import RpcClient

async def main():
    address = os.environ["OPENLET_TEST_RPC"]
    token = os.environ["OPENLET_TEST_INGEST_TOKEN"]
    file = os.environ["OPENLET_TEST_FILE"]
    attempt = Generation(file, 1)
    async with RpcClient(address, "wrong-token-but-valid-shape-123456789", allow_plaintext=True) as rpc:
        try:
            await ProcessingClient(rpc).prepare_parse(attempt)
            raise AssertionError("invalid credential was accepted")
        except AppError as error:
            assert error.reason == "UNAUTHENTICATED" and not error.retryable
            assert "wrong-token" not in str(error)
    async with RpcClient(address, token, allow_plaintext=True) as rpc:
        api = ProcessingClient(rpc)
        prepared = await api.prepare_parse(attempt)
        assert prepared is not None and prepared.inline_content == b""
        content = b"# Report\n"
        upload = await api.prepare_parse_output(attempt, OutputDescription("README.md", "inline", len(content)))
        scope = OutputScope(attempt, "parse", upload.id)
        stale = OutputScope(Generation(file, 2), "parse", upload.id)
        try:
            await api.write_output_bytes(stale, content)
            raise AssertionError("stale generation was accepted")
        except AppError as error:
            assert error.reason == "SOURCE_REPLACED" and not error.retryable
        await api.write_output_bytes(scope, content)
        finalized = await api.complete_output_upload(scope)
        assert finalized.status == "finalized"
        await api.complete_parse(attempt, [upload.id], [])
        assert await api.prepare_parse(attempt) is None
        try:
            await api.fail_index(attempt, "INDEX_FAILED")
            raise AssertionError("dependency exhaustion was accepted")
        except AppError as error:
            assert error.reason == "DEPENDENCY_UNAVAILABLE" and error.retryable
            assert "private" not in str(error)
        task = asyncio.create_task(api.prepare_enrichment(attempt))
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
