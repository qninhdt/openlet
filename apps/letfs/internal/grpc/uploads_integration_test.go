//go:build integration

package grpc

import (
	"bytes"
	"context"
	"crypto/md5"
	"encoding/base64"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/proto"
)

func TestIntegrationUploadPublicationOverAuthenticatedRPC(t *testing.T) {
	db := testfixture.Postgres(t, "../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../packages/contracts/authz/schema.zed")
	endpoint := testfixture.S3(t)
	target, err := url.Parse(endpoint)
	require.NoError(t, err)
	var dropCompletion atomic.Bool
	var completions atomic.Int32
	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.ErrorLog = log.New(io.Discard, "", 0)
	proxy.ModifyResponse = func(response *http.Response) error {
		if response.Request.Method == http.MethodPost && response.Request.URL.Query().Get("uploadId") != "" {
			completions.Add(1)
			if dropCompletion.Swap(false) && response.StatusCode == http.StatusOK {
				_, err := io.Copy(io.Discard, response.Body)
				_ = response.Body.Close()
				if err != nil {
					return err
				}
				return errors.New("test dropped successful multipart completion response")
			}
		}
		return nil
	}
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, _ error) {
		conn, _, err := w.(http.Hijacker).Hijack()
		if err == nil {
			_ = conn.Close()
		}
	}
	control := httptest.NewServer(proxy)
	t.Cleanup(control.Close)
	objectStore, err := storage.New(storage.Config{Endpoint: control.URL, SigningEndpoint: endpoint, Region: "us-east-1", Bucket: "openlet-integration", AccessKey: "integration", SecretKey: "isolated-testcontainers-secret", AllowHTTP: true})
	require.NoError(t, err)
	store := &filesystem.Store{DB: db, Graph: graph, Storage: objectStore, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 20 * 1024 * 1024,
		MaxOutstanding: 20, MaxCleanupBacklog: 20, MultipartThreshold: 5 * 1024 * 1024, MultipartPartBytes: 5 * 1024 * 1024, UploadLifetime: time.Minute, UploadTransferGrace: time.Hour, DownloadLifetime: time.Minute}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	bucketID, fsID := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = store.CreateBucket(owner, uuid.New(), filesystem.CreateBucket{ID: bucketID, LimitBytes: 20 * 1024 * 1024})
	require.NoError(t, err)
	fs, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: fsID, BucketID: bucketID, RootName: "files"})
	require.NoError(t, err)
	const gatewayToken = "isolated-upload-gateway-token-1234567890"
	methods := []string{letfsv1.FilesystemService_CreateUpload_FullMethodName, letfsv1.FilesystemService_GetUpload_FullMethodName,
		letfsv1.FilesystemService_GetUploadParts_FullMethodName, letfsv1.FilesystemService_CompleteUpload_FullMethodName,
		letfsv1.FilesystemService_AbortUpload_FullMethodName, letfsv1.FilesystemService_GetDownload_FullMethodName,
		letfsv1.FilesystemService_UpdateNode_FullMethodName}
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{{Service: "gateway", Token: gatewayToken, Gateway: true, Methods: methods}})
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	server := grpcgo.NewServer(grpcgo.UnaryInterceptor(authentication.Unary()))
	letfsv1.RegisterFilesystemServiceServer(server, &Filesystem{Store: store})
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	connection, err := grpcgo.NewClient(listener.Addr().String(), grpcgo.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	client := letfsv1.NewFilesystemServiceClient(connection)
	actor, other := uuid.New(), uuid.New()
	actorContext := func(id uuid.UUID) context.Context {
		return metadata.NewOutgoingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-user-id", id.String()))
	}
	ctx, foreign := actorContext(actor), actorContext(other)
	paths := &letfsv1.PathContext{Mounts: []*letfsv1.Mount{{Path: "/drive", FilesystemId: fsID.String()}}}
	createRequest := func(name string, data []byte) *letfsv1.CreateUploadRequest {
		t.Helper()
		size := int64(len(data))
		request := &letfsv1.CreateUploadRequest{FilesystemId: fsID.String(), IdempotencyKey: uuid.NewString(), PathContext: paths, SizeBytes: &size, MediaType: "application/octet-stream",
			Target: &letfsv1.CreateUploadRequest_Destination{Destination: &letfsv1.UploadDestination{Name: name, Parent: &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: fs.RootID.String()}}}}}
		if size < store.MultipartThreshold {
			digest := md5.Sum(data)
			checksum := base64.StdEncoding.EncodeToString(digest[:])
			request.ContentMd5 = &checksum
		}
		return request
	}
	httpClient := &http.Client{Timeout: 15 * time.Second}
	put := func(t *testing.T, transfer *letfsv1.SignedUpload, data []byte) string {
		t.Helper()
		require.NotNil(t, transfer)
		require.EqualValues(t, len(data), transfer.ContentLength)
		request, err := http.NewRequestWithContext(t.Context(), http.MethodPut, transfer.Url, bytes.NewReader(data))
		require.NoError(t, err)
		for name, value := range transfer.Headers {
			request.Header.Set(name, value)
		}
		response, err := httpClient.Do(request)
		require.NoError(t, err)
		_, err = io.Copy(io.Discard, response.Body)
		require.NoError(t, response.Body.Close())
		require.NoError(t, err)
		require.Equal(t, http.StatusOK, response.StatusCode)
		return response.Header.Get("ETag")
	}
	content := []byte{0, 255, 1, 2, 3, 4}
	request := createRequest("file.bin", content)
	_, err = client.CreateUpload(ctx, request)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	actions := []authz.Action{authz.UploadCreate, authz.UploadRead, authz.UploadSign, authz.UploadComplete, authz.UploadAbort, authz.ContentRead, authz.NodeUpdate}
	testfixture.Grant(t, graph, "filesystem", fsID, actor, authz.UploadCreate)
	testfixture.Grant(t, graph, "filesystem", fsID, other, actions...)
	missing := proto.Clone(request).(*letfsv1.CreateUploadRequest)
	missing.SizeBytes = nil
	_, err = client.CreateUpload(ctx, missing)
	require.Equal(t, codes.InvalidArgument, status.Code(err))
	created, err := client.CreateUpload(ctx, request)
	require.NoError(t, err)
	uploadID := created.Upload.Id
	require.Equal(t, "single", created.Upload.Transport)
	_, err = client.GetUpload(ctx, &letfsv1.GetUploadRequest{FilesystemId: fsID.String(), UploadId: uploadID})
	require.Equal(t, codes.PermissionDenied, status.Code(err), "create does not grant read")
	_, err = client.CompleteUpload(ctx, &letfsv1.CompleteUploadRequest{FilesystemId: fsID.String(), UploadId: uploadID})
	require.Equal(t, codes.PermissionDenied, status.Code(err), "create does not grant completion")
	testfixture.Grant(t, graph, "filesystem", fsID, actor, actions...)
	replay, err := client.CreateUpload(ctx, request)
	require.NoError(t, err)
	require.Equal(t, uploadID, replay.Upload.Id)
	changed := proto.Clone(request).(*letfsv1.CreateUploadRequest)
	changed.GetDestination().Name = "changed.bin"
	_, err = client.CreateUpload(ctx, changed)
	require.Equal(t, codes.Aborted, status.Code(err))
	_, err = client.GetUpload(foreign, &letfsv1.GetUploadRequest{FilesystemId: fsID.String(), UploadId: uploadID})
	require.Equal(t, codes.NotFound, status.Code(err), "another actor with all upload actions cannot inspect a session")
	_, err = client.CompleteUpload(foreign, &letfsv1.CompleteUploadRequest{FilesystemId: fsID.String(), UploadId: uploadID})
	require.Equal(t, codes.NotFound, status.Code(err))
	_, err = client.AbortUpload(foreign, &letfsv1.AbortUploadRequest{FilesystemId: fsID.String(), UploadId: uploadID})
	require.Equal(t, codes.NotFound, status.Code(err))
	_, err = client.CompleteUpload(ctx, &letfsv1.CompleteUploadRequest{FilesystemId: fsID.String(), UploadId: uploadID})
	require.Equal(t, codes.Aborted, status.Code(err), "missing object cannot publish")
	completing, err := client.CreateUpload(ctx, request)
	require.NoError(t, err)
	require.Equal(t, "completing", completing.Upload.Status)
	require.Nil(t, completing.Upload.Transfer, "completing session cannot renew a write capability")
	put(t, created.Upload.Transfer, content)
	var wg sync.WaitGroup
	results := make(chan *letfsv1.CompleteUploadResponse, 6)
	failures := make(chan error, 6)
	for range 6 {
		wg.Go(func() {
			result, err := client.CompleteUpload(ctx, &letfsv1.CompleteUploadRequest{FilesystemId: fsID.String(), UploadId: uploadID})
			results <- result
			failures <- err
		})
	}
	wg.Wait()
	close(results)
	close(failures)
	for err := range failures {
		require.NoError(t, err)
	}
	var published *letfsv1.UploadPublication
	for result := range results {
		if published == nil {
			published = result.Publication
		}
		require.True(t, proto.Equal(published, result.Publication))
	}
	var used int64
	require.NoError(t, db.QueryRow(t.Context(), `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucketID).Scan(&used))
	require.EqualValues(t, len(content), used)
	final, err := client.CreateUpload(ctx, request)
	require.NoError(t, err)
	require.Nil(t, final.Upload.Transfer)
	require.True(t, proto.Equal(published, final.Upload.GetPublication()))
	changedConfig := *store
	changedConfig.MaxFileBytes = 1
	changedConfig.MultipartThreshold = 1
	trustedActor := identity.WithPrincipal(t.Context(), identity.Principal{ActorID: actor, Service: "gateway", Gateway: true})
	oldInput := filesystem.UploadCreation{SizeBytes: request.SizeBytes, MediaType: request.MediaType, ContentMD5: request.ContentMd5,
		Destination: &filesystem.UploadDestination{Parent: filesystem.Locator{NodeID: fs.RootID}, Name: request.GetDestination().Name}}
	oldReceipt, err := changedConfig.CreateUpload(trustedActor, fsID, []filesystem.Mount{{Path: "/drive", FilesystemID: fsID}}, uuid.MustParse(request.IdempotencyKey), oldInput)
	require.NoError(t, err, "new transfer limits cannot reinterpret a saved admission receipt")
	require.Equal(t, "finalized", oldReceipt.State)
	require.Nil(t, oldReceipt.Transfer)
	_, err = client.AbortUpload(ctx, &letfsv1.AbortUploadRequest{FilesystemId: fsID.String(), UploadId: uploadID})
	require.Equal(t, codes.Aborted, status.Code(err))
	download, err := client.GetDownload(ctx, &letfsv1.GetDownloadRequest{FilesystemId: fsID.String(), NodeId: published.NodeId, PathContext: paths})
	require.NoError(t, err)
	get, err := http.NewRequestWithContext(t.Context(), http.MethodGet, download.Download.GetSignedUrl(), nil)
	require.NoError(t, err)
	response, err := httpClient.Do(get)
	require.NoError(t, err)
	actual, err := io.ReadAll(response.Body)
	require.NoError(t, response.Body.Close())
	require.NoError(t, err)
	require.Equal(t, content, actual)
	expectedUsed := int64(len(content))

	t.Run("stale overwrite retains content and cleanup", func(t *testing.T) {
		replacement := createRequest("unused", []byte{9})
		replacement.Target = &letfsv1.CreateUploadRequest_Replacement{Replacement: &letfsv1.UploadReplacement{Locator: &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: published.NodeId}}, Revision: &published.Revision}}
		prepared, err := client.CreateUpload(ctx, replacement)
		require.NoError(t, err)
		name := "renamed.bin"
		_, err = client.UpdateNode(ctx, &letfsv1.UpdateNodeRequest{FilesystemId: fsID.String(), PathContext: paths, Locator: replacement.GetReplacement().Locator, Revision: &published.Revision, Name: &name})
		require.NoError(t, err)
		put(t, prepared.Upload.Transfer, []byte{9})
		_, err = client.CompleteUpload(ctx, &letfsv1.CompleteUploadRequest{FilesystemId: fsID.String(), UploadId: prepared.Upload.Id})
		require.Equal(t, codes.FailedPrecondition, status.Code(err))
		state, err := client.GetUpload(ctx, &letfsv1.GetUploadRequest{FilesystemId: fsID.String(), UploadId: prepared.Upload.Id})
		require.NoError(t, err)
		require.Equal(t, "aborted", state.Upload.Status)
		var safe bool
		require.NoError(t, db.QueryRow(t.Context(), `SELECT d.ambiguous_write AND d.eligible_at>=u.transfer_deadline FROM object_deletions d JOIN uploads u ON u.candidate_key=d.object_key WHERE u.id=$1`, prepared.Upload.Id).Scan(&safe))
		require.True(t, safe, "late signed PUT remains fenced from cleanup")
		require.NoError(t, db.QueryRow(t.Context(), `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucketID).Scan(&used))
		require.EqualValues(t, len(content), used)
		var retained bool
		require.NoError(t, db.QueryRow(t.Context(), `SELECT f.object_key=u.candidate_key FROM files f JOIN uploads u ON u.id=$1 WHERE f.node_id=$2`, uploadID, published.NodeId).Scan(&retained))
		require.True(t, retained, "stale overwrite cannot replace the original object")
	})

	t.Run("overwrite preserves identity and adjusts quota once", func(t *testing.T) {
		var revision int64
		require.NoError(t, db.QueryRow(t.Context(), `SELECT revision FROM nodes WHERE id=$1`, published.NodeId).Scan(&revision))
		data := []byte{7, 8, 9}
		replacement := createRequest("unused", data)
		replacement.Target = &letfsv1.CreateUploadRequest_Replacement{Replacement: &letfsv1.UploadReplacement{Locator: &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: published.NodeId}}, Revision: &revision}}
		prepared, err := client.CreateUpload(ctx, replacement)
		require.NoError(t, err)
		put(t, prepared.Upload.Transfer, data)
		result, err := client.CompleteUpload(ctx, &letfsv1.CompleteUploadRequest{FilesystemId: fsID.String(), UploadId: prepared.Upload.Id})
		require.NoError(t, err)
		require.Equal(t, published.NodeId, result.Publication.NodeId)
		require.Equal(t, revision+1, result.Publication.Revision)
		var count int64
		require.NoError(t, db.QueryRow(t.Context(), `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucketID).Scan(&used))
		require.EqualValues(t, len(data), used)
		require.NoError(t, db.QueryRow(t.Context(), `SELECT node_count FROM filesystems WHERE id=$1`, fsID).Scan(&count))
		require.EqualValues(t, 2, count)
		var queued bool
		require.NoError(t, db.QueryRow(t.Context(), `SELECT EXISTS(SELECT 1 FROM object_deletions d JOIN uploads u ON u.candidate_key=d.object_key WHERE u.id=$1)`, uploadID).Scan(&queued))
		require.True(t, queued, "the replaced object retains cleanup evidence")
		expectedUsed = int64(len(data))
	})

	t.Run("multipart completion survives lost response", func(t *testing.T) {
		first := bytes.Repeat([]byte{0, 255}, 5*1024*1024/2)
		last := []byte{1, 2, 3, 4}
		multiRequest := createRequest("multipart.bin", append(append([]byte{}, first...), last...))
		multi, err := client.CreateUpload(ctx, multiRequest)
		require.NoError(t, err)
		require.Equal(t, "multipart", multi.Upload.Transport)
		require.EqualValues(t, 2, *multi.Upload.PartCount)
		partsRequest := &letfsv1.GetUploadPartsRequest{FilesystemId: fsID.String(), UploadId: multi.Upload.Id, Numbers: []int32{1, 1}}
		_, err = client.GetUploadParts(ctx, partsRequest)
		require.Equal(t, codes.InvalidArgument, status.Code(err))
		partsRequest.Numbers = []int32{0}
		_, err = client.GetUploadParts(ctx, partsRequest)
		require.Equal(t, codes.InvalidArgument, status.Code(err))
		partsRequest.Numbers = []int32{1, 2}
		parts, err := client.GetUploadParts(ctx, partsRequest)
		require.NoError(t, err)
		completion := &letfsv1.CompleteUploadRequest{FilesystemId: fsID.String(), UploadId: multi.Upload.Id}
		for i, data := range [][]byte{first, last} {
			completion.Parts = append(completion.Parts, &letfsv1.PartReceipt{PartNumber: int32(i + 1), Etag: put(t, parts.Items[i].Transfer, data)})
		}
		dropCompletion.Store(true)
		result, err := client.CompleteUpload(ctx, completion)
		require.NoError(t, err, "HEAD reconciles the completed unique object after lost acknowledgment")
		require.EqualValues(t, 1, completions.Load(), "SDK did not retry the unknown completion")
		replayed, err := client.CompleteUpload(ctx, completion)
		require.NoError(t, err)
		require.True(t, proto.Equal(result, replayed))
		completion.Parts[0].Etag = "different"
		_, err = client.CompleteUpload(ctx, completion)
		require.Equal(t, codes.Aborted, status.Code(err), "frozen receipts cannot change after publication")
		_, err = client.GetUploadParts(ctx, partsRequest)
		require.Equal(t, codes.Aborted, status.Code(err), "terminal session cannot renew capability")
		require.NoError(t, db.QueryRow(t.Context(), `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucketID).Scan(&used))
		expectedUsed += int64(len(first) + len(last))
		require.Equal(t, expectedUsed, used)
	})

	t.Run("quota rejection aborts unpublished bytes", func(t *testing.T) {
		_, err := db.Exec(t.Context(), `UPDATE quota_buckets SET limit_bytes=used_bytes WHERE id=$1`, bucketID)
		require.NoError(t, err)
		data := []byte{1, 2}
		prepared, err := client.CreateUpload(ctx, createRequest("over-quota.bin", data))
		require.NoError(t, err)
		put(t, prepared.Upload.Transfer, data)
		_, err = client.CompleteUpload(ctx, &letfsv1.CompleteUploadRequest{FilesystemId: fsID.String(), UploadId: prepared.Upload.Id})
		require.Equal(t, codes.Aborted, status.Code(err))
		var state string
		require.NoError(t, db.QueryRow(t.Context(), `SELECT state FROM uploads WHERE id=$1`, prepared.Upload.Id).Scan(&state))
		require.Equal(t, "aborted", state)
		require.NoError(t, db.QueryRow(t.Context(), `SELECT used_bytes FROM quota_buckets WHERE id=$1`, bucketID).Scan(&used))
		require.Equal(t, expectedUsed, used)
		var published bool
		require.NoError(t, db.QueryRow(t.Context(), `SELECT EXISTS(SELECT 1 FROM nodes WHERE filesystem_id=$1 AND name='over-quota.bin')`, fsID).Scan(&published))
		require.False(t, published)
	})

	t.Run("expiration and frozen bucket still allow abort", func(t *testing.T) {
		expiredRequest := createRequest("expired.bin", []byte{1})
		expired, err := client.CreateUpload(ctx, expiredRequest)
		require.NoError(t, err)
		_, err = db.Exec(t.Context(), `UPDATE uploads SET expires_at=now()-interval '1 second' WHERE id=$1`, expired.Upload.Id)
		require.NoError(t, err)
		replay, err := client.CreateUpload(ctx, expiredRequest)
		require.NoError(t, err)
		require.Nil(t, replay.Upload.Transfer)
		_, err = client.CompleteUpload(ctx, &letfsv1.CompleteUploadRequest{FilesystemId: fsID.String(), UploadId: expired.Upload.Id})
		require.Equal(t, codes.Aborted, status.Code(err))
		_, err = store.FreezeBucket(owner, uuid.New(), bucketID)
		require.NoError(t, err)
		_, err = client.AbortUpload(ctx, &letfsv1.AbortUploadRequest{FilesystemId: fsID.String(), UploadId: expired.Upload.Id})
		require.NoError(t, err, "cleanup survives owner freeze")
		_, err = client.AbortUpload(ctx, &letfsv1.AbortUploadRequest{FilesystemId: fsID.String(), UploadId: expired.Upload.Id})
		require.NoError(t, err)
	})
}
