//go:build integration

package grpc

import (
	"context"
	"net"
	"net/url"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
	letfsclient "github.com/qninhdt/openlet/packages/go/clients/letfs"
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
	"google.golang.org/protobuf/encoding/protojson"
)

func TestIntegrationFilesystemOperationsOverAuthenticatedRPC(t *testing.T) {
	db := testfixture.Postgres(t, "../../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../../packages/contracts/authz/schema.zed")
	store := &filesystem.Store{DB: db, Graph: graph, MaxNodes: 100, InlineLimit: 64, MaxFileBytes: 64}
	signer, err := storage.New(storage.Config{Endpoint: "https://internal.invalid", SigningEndpoint: "https://browser.invalid", Region: "us-east-1",
		Bucket: "isolated", AccessKey: "test-access", SecretKey: "isolated-test-secret"})
	require.NoError(t, err)
	store.Storage, store.DownloadLifetime = signer, 5*time.Minute
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "resource-owner"})
	bucketID, fsID := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	_, err = store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: bucketID, LimitBytes: 100})
	require.NoError(t, err)
	fs, err := createTestScope(owner, store, uuid.New(), bucketID, fsID)
	require.NoError(t, err)
	file := uuid.Must(uuid.NewV7())
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,scope_id,parent_id,name,kind,revision) VALUES($1,$2,$3,'report.txt','file',9223372036854775807)`, file, fsID, fs.RootID)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,inline_bytes,media_type,context) VALUES($1,'inline',''::bytea,'text/plain','detail')`, file)
	require.NoError(t, err)
	actor := uuid.New()
	testfixture.Grant(t, graph, "scope", fsID, actor, authz.ScopeReadMetadata, authz.ScopeReadMetadata)
	const gatewayToken = "isolated-read-gateway-token-1234567890"
	const serviceToken = "isolated-nondelegating-token-12345678"
	const delegatedToken = "isolated-delegating-token-12345678901"
	methods := []string{letfsv1.FilesystemService_GetFilesystem_FullMethodName, letfsv1.FilesystemService_GetNode_FullMethodName,
		letfsv1.FilesystemService_ResolveNode_FullMethodName, letfsv1.FilesystemService_BatchStat_FullMethodName, letfsv1.FilesystemService_ListNodes_FullMethodName,
		letfsv1.FilesystemService_CreateNode_FullMethodName, letfsv1.FilesystemService_UpdateNode_FullMethodName,
		letfsv1.FilesystemService_ReplaceContent_FullMethodName, letfsv1.FilesystemService_GetDownload_FullMethodName, letfsv1.FilesystemService_TrashNode_FullMethodName,
		letfsv1.FilesystemService_GetTrash_FullMethodName, letfsv1.FilesystemService_ListTrash_FullMethodName, letfsv1.FilesystemService_RestoreTrash_FullMethodName,
		letfsv1.FilesystemService_SearchFiles_FullMethodName, letfsv1.FilesystemService_SemanticSearch_FullMethodName}
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{
		{Service: "gateway", Token: gatewayToken, Gateway: true, Methods: methods},
		{Service: "background", Token: serviceToken, Methods: methods},
		{Service: "workspace", Token: delegatedToken, DelegateActor: true, Methods: methods},
	})
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	server := grpcgo.NewServer(grpcgo.UnaryInterceptor(authentication.Unary()))
	letfsv1.RegisterFilesystemServiceServer(server, &Filesystem{Store: store, Service: &filesystem.Service{Store: store}})
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	connection, err := grpcgo.NewClient(listener.Addr().String(), grpcgo.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	client := letfsv1.NewFilesystemServiceClient(connection)
	ctx := metadata.NewOutgoingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-user-id", actor.String()))

	denied := metadata.NewOutgoingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-user-id", uuid.NewString()))
	request := &letfsv1.GetNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), NodeId: file.String()}
	node, err := client.GetNode(ctx, request)
	require.NoError(t, err)
	delegated := metadata.NewOutgoingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+delegatedToken, "x-openlet-user-id", actor.String()))
	delegatedNode, err := client.GetNode(delegated, request)
	require.NoError(t, err, "authorized services may delegate an actor without impersonating the gateway")
	require.Equal(t, node.Node.Id, delegatedNode.Node.Id)
	nativeConnection, err := rpc.Dial(listener.Addr().String(), delegatedToken, rpc.Transport{AllowPlaintext: true})
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, nativeConnection.Close()) })
	nativeClient := letfsclient.FilesystemClient{API: letfsv1.NewFilesystemServiceClient(nativeConnection)}

	nativeContext, err := rpc.WithActor(t.Context(), identity.Actor{Kind: identity.User, ID: actor})
	require.NoError(t, err)
	native, err := nativeClient.GetNode(nativeContext, bucketID, fsID, file)
	require.NoError(t, err)
	require.Equal(t, file, native.ID)
	require.Equal(t, int64(9223372036854775807), native.Revision)
	nativePage, err := nativeClient.ListNodes(nativeContext, bucketID, fsID, *fs.RootID, 100, nil)
	require.NoError(t, err)
	require.Len(t, nativePage.Items, 1)
	require.Equal(t, file, nativePage.Items[0].ID)
	foreignContext, err := rpc.WithActor(t.Context(), identity.Actor{Kind: identity.User, ID: uuid.New()})
	require.NoError(t, err)
	_, err = nativeClient.GetNode(foreignContext, bucketID, fsID, file)
	require.Equal(t, apperr.Forbidden, apperr.KindOf(err), "owner checks delegated actor permission")

	require.Equal(t, int64(9223372036854775807), node.Node.Revision)
	require.Nil(t, node.Node.Context, "metadata omits semantic context")
	require.Equal(t, fs.RootID.String(), *node.Node.ParentId)
	encoded, err := protojson.Marshal(node)
	require.NoError(t, err)
	require.Contains(t, string(encoded), `"revision":"9223372036854775807"`)
	locator := &letfsv1.Locator{Target: &letfsv1.Locator_Path{Path: &letfsv1.PathLocator{Path: "/report.txt"}}}
	_, err = client.ResolveNode(denied, &letfsv1.ResolveNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Locator: locator})
	require.Equal(t, codes.PermissionDenied, status.Code(err), "ungranted actor cannot resolve scope paths")
	testfixture.Grant(t, graph, "scope", fsID, actor, authz.ScopeReadMetadata)
	resolved, err := client.ResolveNode(ctx, &letfsv1.ResolveNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Locator: locator})
	require.NoError(t, err)
	require.Equal(t, node.Node.Id, resolved.Node.Id)
	batch, err := client.BatchStat(ctx, &letfsv1.BatchStatRequest{FilesystemId: bucketID.String(), Locators: []*letfsv1.ScopedLocator{{ScopeId: fsID.String(), Locator: locator}, {ScopeId: fsID.String(), Locator: locator}}})
	require.NoError(t, err)
	require.Len(t, batch.Items, 2)
	listed, err := client.ListNodes(ctx, &letfsv1.ListNodesRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Parent: &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: fs.RootID.String()}}})
	require.NoError(t, err)
	require.Len(t, listed.Items, 1)
	require.Nil(t, listed.Items[0].Context)
	require.Nil(t, listed.NextCursor)
	searchRequest := &letfsv1.SearchFilesRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Query: "report"}
	_, err = client.SearchFiles(denied, searchRequest)
	require.Equal(t, codes.PermissionDenied, status.Code(err), "ungranted actor cannot search content")
	semanticRequest := &letfsv1.SemanticSearchRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Query: "report"}
	_, err = client.SemanticSearch(denied, semanticRequest)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	testfixture.Grant(t, graph, "scope", fsID, actor, authz.ScopeReadContent)
	searchPage, err := client.SearchFiles(ctx, searchRequest)
	require.NoError(t, err)
	require.Len(t, searchPage.Items, 1)
	require.Equal(t, file.String(), searchPage.Items[0].Node.Id)
	require.Equal(t, "/report.txt", searchPage.Items[0].Path)
	require.Nil(t, searchPage.Items[0].Node.Context)
	_, err = client.SemanticSearch(ctx, semanticRequest)
	require.Equal(t, codes.Unavailable, status.Code(err), "provider absence is a dependency error after authorization")
	root, err := client.GetNode(ctx, &letfsv1.GetNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), NodeId: fs.RootID.String()})
	require.NoError(t, err)
	require.Nil(t, root.Node.ParentId)
	require.Nil(t, root.Node.MediaType)
	downloadRequest := &letfsv1.GetDownloadRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), NodeId: file.String()}
	_, err = client.GetDownload(denied, downloadRequest)
	require.Equal(t, codes.PermissionDenied, status.Code(err), "ungranted actor cannot read content")
	testfixture.Grant(t, graph, "scope", fsID, actor, authz.ScopeReadContent)
	download, err := client.GetDownload(ctx, downloadRequest)
	require.NoError(t, err)
	require.IsType(t, &letfsv1.Download_InlineContent{}, download.Download.Source, "empty bytes keep their oneof discriminator over RPC")
	require.Empty(t, download.Download.GetInlineContent())
	require.Equal(t, `"9223372036854775807"`, download.Download.Etag)
	require.Equal(t, "text/plain", download.Download.Mime)
	require.Equal(t, "report.txt", download.Download.Filename)
	downloadRequest.Revision = new(int64)
	_, err = client.GetDownload(ctx, downloadRequest)
	require.Equal(t, codes.InvalidArgument, status.Code(err))
	*downloadRequest.Revision = 1
	_, err = client.GetDownload(ctx, downloadRequest)
	require.Equal(t, codes.FailedPrecondition, status.Code(err))
	*downloadRequest.Revision = node.Node.Revision
	_, err = client.GetDownload(ctx, downloadRequest)
	require.NoError(t, err)
	_, err = (&Filesystem{Store: store}).GetDownload(context.Background(), downloadRequest)
	require.Equal(t, apperr.Unauthenticated, apperr.KindOf(err))
	_, err = client.GetDownload(ctx, &letfsv1.GetDownloadRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), NodeId: fs.RootID.String()})
	require.Equal(t, codes.Aborted, status.Code(err), "directory has no file payload")
	objectID := uuid.Must(uuid.NewV7())
	_, err = db.Exec(t.Context(), `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'Báo cáo.pdf','file',6)`, objectID, fsID, fs.RootID)
	require.NoError(t, err)
	_, err = db.Exec(t.Context(), `INSERT INTO files(node_id,storage_kind,object_key) VALUES($1,'object','candidate/object')`, objectID)
	require.NoError(t, err)
	objectRequest := &letfsv1.GetDownloadRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), NodeId: objectID.String()}
	object, err := client.GetDownload(ctx, objectRequest)
	require.NoError(t, err)
	require.IsType(t, &letfsv1.Download_SignedUrl{}, object.Download.Source)
	require.Equal(t, "application/octet-stream", object.Download.Mime)
	require.EqualValues(t, 6, object.Download.SizeBytes)
	objectURL, err := url.Parse(object.Download.GetSignedUrl())
	require.NoError(t, err)
	require.Equal(t, "browser.invalid", objectURL.Host)
	require.Equal(t, "/isolated/candidate/object", objectURL.Path)
	require.Equal(t, "300", objectURL.Query().Get("X-Amz-Expires"))
	objectRequest.ScopeId = uuid.NewString()
	_, err = client.GetDownload(ctx, objectRequest)
	require.Equal(t, codes.NotFound, status.Code(err), "scope identity cannot replace filesystem authority")
	_, err = client.ResolveNode(ctx, &letfsv1.ResolveNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Locator: &letfsv1.Locator{}})
	require.Equal(t, codes.InvalidArgument, status.Code(err), "unset oneof never means root")
	_, err = client.ListNodes(ctx, &letfsv1.ListNodesRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Parent: locator, Limit: new(int32)})
	require.Equal(t, codes.InvalidArgument, status.Code(err), "present zero limit differs from omitted default")

	for _, test := range []struct {
		md   metadata.MD
		code codes.Code
	}{
		{metadata.MD{}, codes.Unauthenticated},
		{metadata.Pairs("authorization", "Bearer "+gatewayToken), codes.Unauthenticated},
		{metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-user-id", actor.String(), "x-openlet-user-id", uuid.NewString()), codes.Unauthenticated},
		{metadata.Pairs("authorization", "Bearer "+gatewayToken, "x-openlet-user-id", uuid.NewString()), codes.PermissionDenied},
		{metadata.Pairs("authorization", "Bearer "+serviceToken, "x-openlet-user-id", actor.String()), codes.PermissionDenied},
		{metadata.Pairs("authorization", "Bearer "+serviceToken), codes.Unauthenticated},
	} {
		_, err := client.GetNode(metadata.NewOutgoingContext(t.Context(), test.md), request)
		require.Equal(t, test.code, status.Code(err))
	}
	_, err = (&Filesystem{Store: store}).GetNode(context.Background(), request)
	require.Equal(t, apperr.Unauthenticated, apperr.KindOf(err), "direct adapter cannot bypass application admission")

	creation := &letfsv1.CreateNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), IdempotencyKey: uuid.NewString(),
		Input: &letfsv1.CreateNodeRequest_File{File: &letfsv1.InlineFileCreation{Name: "binary.bin", Content: []byte{0, 255, 1}, MediaType: "application/octet-stream",
			Parent: &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: fs.RootID.String()}}}}}
	_, err = client.CreateNode(ctx, creation)
	require.Equal(t, codes.PermissionDenied, status.Code(err), "read action cannot mutate")
	testfixture.Grant(t, graph, "scope", fsID, actor, authz.ScopeWrite, authz.ScopeWrite, authz.ScopeWrite, authz.ScopeTrash, authz.ScopeReadMetadata, authz.ScopeRestore)
	box, err := client.CreateNode(ctx, &letfsv1.CreateNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), IdempotencyKey: uuid.NewString(),
		Input: &letfsv1.CreateNodeRequest_Directory{Directory: &letfsv1.DirectoryCreation{Name: "box", Parent: &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: fs.RootID.String()}}}}})
	require.NoError(t, err)
	boxID := box.Node.Id
	bound := &letfsv1.Locator{Target: &letfsv1.Locator_Path{Path: &letfsv1.PathLocator{Path: "/"}}, RootId: &boxID}
	resolved, err = client.ResolveNode(ctx, &letfsv1.ResolveNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Locator: bound})
	require.NoError(t, err)
	require.Equal(t, boxID, resolved.Node.Id)
	artifact := uuid.Must(uuid.NewV7())
	_, err = db.Exec(ctx, `INSERT INTO nodes(id,scope_id,parent_id,name,kind) VALUES($1,$2,$3,'parts','directory')`, artifact, fsID, file)
	require.NoError(t, err)
	children, err := client.ListNodes(ctx, &letfsv1.ListNodesRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Parent: &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: file.String()}}})
	require.NoError(t, err)
	require.Len(t, children.Items, 1)
	require.True(t, children.Items[0].Readonly)
	require.Equal(t, "directory", children.Items[0].Kind)
	for _, path := range []string{"/../report.txt", "/@" + file.String()} {
		bound.Target = &letfsv1.Locator_Path{Path: &letfsv1.PathLocator{Path: path}}
		_, err = client.ResolveNode(ctx, &letfsv1.ResolveNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Locator: bound})
		require.Equal(t, codes.NotFound, status.Code(err))
	}
	bound.Target = &letfsv1.Locator_NodeId{NodeId: file.String()}
	_, err = client.ReplaceContent(ctx, &letfsv1.ReplaceContentRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Locator: bound, Revision: &node.Node.Revision, Content: []byte("blocked"), MediaType: "text/plain"})
	require.Equal(t, codes.NotFound, status.Code(err), "direct RPC cannot write outside supplied root")
	created, err := client.CreateNode(ctx, creation)
	require.NoError(t, err)
	require.EqualValues(t, 3, created.Node.SizeBytes)
	var content []byte
	require.NoError(t, db.QueryRow(t.Context(), `SELECT inline_bytes FROM files WHERE node_id=$1`, created.Node.Id).Scan(&content))
	require.Equal(t, []byte{0, 255, 1}, content)
	binary, err := client.GetDownload(ctx, &letfsv1.GetDownloadRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), NodeId: created.Node.Id})
	require.NoError(t, err)
	require.Equal(t, []byte{0, 255, 1}, binary.Download.GetInlineContent())
	replayed, err := client.CreateNode(ctx, creation)
	require.NoError(t, err)
	require.Equal(t, created.Node.Id, replayed.Node.Id)
	newName := "renamed.bin"
	patch := &letfsv1.UpdateNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), Locator: &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: created.Node.Id}}, Name: &newName}
	_, err = client.UpdateNode(ctx, patch)
	require.Equal(t, codes.FailedPrecondition, status.Code(err), "unset revision must not mean revision zero")
	patch.Revision = &created.Node.Revision
	updated, err := client.UpdateNode(ctx, patch)
	require.NoError(t, err)
	require.Equal(t, newName, updated.Node.Name)
	require.EqualValues(t, 2, updated.Node.Revision)
	_, err = client.UpdateNode(ctx, patch)
	require.Equal(t, codes.FailedPrecondition, status.Code(err), "old revision cannot mutate twice")
	replaced, err := client.ReplaceContent(ctx, &letfsv1.ReplaceContentRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(),
		Locator: patch.Locator, Revision: &updated.Node.Revision, Content: []byte{}, MediaType: "application/octet-stream"})
	require.NoError(t, err)
	require.Zero(t, replaced.Node.SizeBytes)
	require.NoError(t, db.QueryRow(t.Context(), `SELECT inline_bytes FROM files WHERE node_id=$1`, created.Node.Id).Scan(&content))
	require.NotNil(t, content)
	require.Empty(t, content)
	trashed, err := client.TrashNode(ctx, &letfsv1.TrashNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(),
		Locator: patch.Locator, Revision: &replaced.Node.Revision})
	require.NoError(t, err)
	require.Equal(t, actor.String(), trashed.Entry.ActorId)
	_, err = client.GetNode(ctx, &letfsv1.GetNodeRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), NodeId: created.Node.Id})
	require.Equal(t, codes.NotFound, status.Code(err))
	_, err = client.GetDownload(ctx, &letfsv1.GetDownloadRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), NodeId: created.Node.Id})
	require.Equal(t, codes.NotFound, status.Code(err), "detached content is hidden by raw ID")
	entry, err := client.GetTrash(ctx, &letfsv1.GetTrashRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), EntryId: trashed.Entry.Id})
	require.NoError(t, err)
	require.Equal(t, created.Node.Id, entry.Entry.NodeId)
	trash, err := client.ListTrash(ctx, &letfsv1.ListTrashRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String()})
	require.NoError(t, err)
	require.Len(t, trash.Items, 1)
	restored, err := client.RestoreTrash(ctx, &letfsv1.RestoreTrashRequest{FilesystemId: bucketID.String(), ScopeId: fsID.String(), EntryId: trashed.Entry.Id})
	require.NoError(t, err)
	require.Equal(t, created.Node.Id, restored.Node.Id)
	require.EqualValues(t, 5, restored.Node.Revision)
	restricted, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: uuid.Must(uuid.NewV7()), LimitBytes: 100})
	require.NoError(t, err)
	testfixture.Grant(t, graph, "filesystem", restricted.ID, actor, authz.FilesystemRead)
	metadata, err := nativeClient.GetFilesystem(nativeContext, restricted.ID)
	require.NoError(t, err)
	require.Equal(t, restricted.ID, metadata.ID)
}
