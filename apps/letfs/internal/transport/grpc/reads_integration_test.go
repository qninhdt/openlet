//go:build integration

package grpc

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"image"
	"image/png"
	"net"
	"sync/atomic"
	"testing"

	v1 "github.com/authzed/authzed-go/proto/authzed/api/v1"
	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/apps/letfs/internal/testfixture"
	"github.com/qninhdt/openlet/packages/go/authz"
	letfsclient "github.com/qninhdt/openlet/packages/go/clients/letfs"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/identity"
	"github.com/qninhdt/openlet/packages/go/rpc"
	sharedfixture "github.com/qninhdt/openlet/packages/go/testfixture"
	"github.com/stretchr/testify/require"
	"golang.org/x/sync/semaphore"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

func TestIntegrationNativeReadsWithLetaCredential(t *testing.T) {
	db := testfixture.Postgres(t, "../../../migrations/0001_initial.sql")
	graph, _, _ := sharedfixture.SpiceDB(t, "../../../../../packages/contracts/authz/schema.zed")
	store := &filesystem.Store{DB: db, Graph: graph, MaxNodes: 100, MaxCopyNodes: 100, MaxOutstanding: 100, MaxCleanupBacklog: 100, InlineLimit: 1048576, MaxFileBytes: 104857600, ImageSlots: semaphore.NewWeighted(2)}
	owner := identity.WithPrincipal(t.Context(), identity.Principal{Service: "workspace"})
	fs, scope, user, leta := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7()), uuid.New(), uuid.New()
	_, err := store.CreateFilesystem(owner, uuid.New(), filesystem.CreateFilesystem{ID: fs, LimitBytes: 1 << 24})
	require.NoError(t, err)
	scopes, err := store.CreateScopes(owner, uuid.New(), fs, []uuid.UUID{scope}, true, true)
	require.NoError(t, err)
	testfixture.Grant(t, graph, "scope", scope, user, authz.ScopeWrite)
	_, err = graph.WriteRelationships(t.Context(), &v1.WriteRelationshipsRequest{Updates: []*v1.RelationshipUpdate{{Operation: v1.RelationshipUpdate_OPERATION_TOUCH, Relationship: &v1.Relationship{Resource: &v1.ObjectReference{ObjectType: "scope", ObjectId: scope.String()}, Relation: "editor", Subject: &v1.SubjectReference{Object: &v1.ObjectReference{ObjectType: "leta", ObjectId: leta.String()}}}}}})
	require.NoError(t, err)
	actor := identity.WithPrincipal(t.Context(), identity.Principal{ActorKind: identity.User, ActorID: user, Service: "gateway", Gateway: true})
	box, err := store.CreateNode(actor, scope, uuid.New(), filesystem.CreateNode{Parent: filesystem.Locator{NodeID: scopes[0].RootID}, Name: "box"})
	require.NoError(t, err)
	text, err := store.CreateNode(actor, scope, uuid.New(), filesystem.CreateNode{Parent: filesystem.Locator{NodeID: &box.ID}, Name: "notes.txt", File: &filesystem.InlineFile{Content: []byte("alpha\nbeta\n"), MediaType: "text/plain"}})
	require.NoError(t, err)
	var pngBody bytes.Buffer
	require.NoError(t, png.Encode(&pngBody, image.NewNRGBA(image.Rect(0, 0, 2, 1))))
	imageNode, err := store.CreateNode(actor, scope, uuid.New(), filesystem.CreateNode{Parent: filesystem.Locator{NodeID: &box.ID}, Name: "image.png", File: &filesystem.InlineFile{Content: pngBody.Bytes(), MediaType: "image/png"}})
	require.NoError(t, err)
	const token = "isolated-native-reads-leta-token-123456"
	authentication, err := rpc.NewAuthenticator([]rpc.Credential{LetaCredential(token)})
	require.NoError(t, err)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	require.NoError(t, err)
	var loseAppendResponse atomic.Bool
	server := grpcgo.NewServer(grpcgo.ChainUnaryInterceptor(authentication.Unary(), func(ctx context.Context, req any, info *grpcgo.UnaryServerInfo, handler grpcgo.UnaryHandler) (any, error) {
		result, err := handler(ctx, req)
		if err == nil && info.FullMethod == letfsv1.FilesystemService_AppendText_FullMethodName && loseAppendResponse.Swap(false) {
			return nil, status.Error(codes.Unavailable, "injected response loss after commit")
		}
		return result, err
	}))
	letfsv1.RegisterFilesystemServiceServer(server, &Filesystem{Store: store, Service: &filesystem.Service{Store: store}})
	done := make(chan error, 1)
	go func() { done <- server.Serve(listener) }()
	t.Cleanup(func() { server.Stop(); require.NoError(t, <-done) })
	connection, err := grpcgo.NewClient(listener.Addr().String(), grpcgo.WithTransportCredentials(insecure.NewCredentials()))
	require.NoError(t, err)
	t.Cleanup(func() { require.NoError(t, connection.Close()) })
	api := letfsv1.NewFilesystemServiceClient(connection)
	client := letfsclient.FilesystemClient{API: api}
	ctx := metadata.NewOutgoingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+token, "x-openlet-leta-id", leta.String()))
	path := "/notes.txt"
	loc := letfsclient.Locator{Path: &path, RootID: &box.ID}
	stat, err := client.Stat(ctx, fs, scope, loc, true)
	require.NoError(t, err)
	require.Equal(t, text.ID, stat.Node.ID)
	require.EqualValues(t, 11, stat.ReadableSize)
	searchRoot := "/"
	searchLocator := letfsclient.Locator{Path: &searchRoot, RootID: &box.ID}
	candidates, err := client.TextSearch(ctx, fs, scope, searchLocator, letfsclient.TextSearchOptions{Mode: "files", Text: "alpha"})
	require.NoError(t, err)
	require.True(t, candidates.Complete)
	require.Len(t, candidates.Items, 2)
	require.Equal(t, "image.png", candidates.Items[0].Path, "blob metadata remains a safe candidate")
	require.Equal(t, "notes.txt", candidates.Items[1].Path)
	lines, err := client.TextSearch(ctx, fs, scope, loc, letfsclient.TextSearchOptions{Mode: "lines", Text: "beta"})
	require.NoError(t, err)
	require.Equal(t, []byte("beta\n"), lines.Content)
	require.Equal(t, stat.Fingerprint, lines.Stat.Fingerprint)
	for _, options := range []letfsclient.TextSearchOptions{{Mode: "files", Text: "alpha", MaxFiles: new(int32(1))}, {Mode: "lines", Text: "beta", MaxBytes: new(int32(1))}} {
		queryLocator := loc
		if options.Mode == "files" {
			queryLocator = searchLocator
		}
		limited, err := client.TextSearch(ctx, fs, scope, queryLocator, options)
		require.NoError(t, err)
		require.False(t, limited.Complete)
		require.Empty(t, limited.Items)
		require.Empty(t, limited.Content)
		require.Nil(t, limited.Stat)
	}
	_, err = client.TextSearch(ctx, fs, scope, letfsclient.Locator{NodeID: scopes[0].RootID, RootID: &box.ID}, letfsclient.TextSearchOptions{Mode: "files", Text: "alpha"})
	require.Error(t, err)
	for _, selection := range []letfsclient.TextSelection{{Kind: "whole"}, {Kind: "bytes", Offset: 6}, {Kind: "lines", StartLine: 2, LineCount: 1}, {Kind: "tail", LineCount: 1}, {Kind: "head", LineCount: 1}} {
		read, err := client.ReadText(ctx, fs, scope, loc, selection, &stat.Fingerprint)
		require.NoError(t, err)
		want := "beta\n"
		if selection.Kind == "whole" {
			want = "alpha\nbeta\n"
		} else if selection.Kind == "head" {
			want = "alpha\n"
		}
		require.Equal(t, []byte(want), read.Content)
		require.Equal(t, stat.Fingerprint, read.Stat.Fingerprint)
	}
	metric, err := client.TextMetrics(ctx, fs, scope, loc, "sha256")
	require.NoError(t, err)
	require.Equal(t, *stat.SHA256, metric.Digest)
	root := "/"
	page, err := client.ReadTree(ctx, fs, scope, letfsclient.Locator{Path: &root, RootID: &box.ID}, letfsclient.TreeOptions{})
	require.NoError(t, err)
	require.True(t, page.Complete)
	require.Len(t, page.Items, 2)
	require.Equal(t, "image.png", page.Items[0].Path)
	listed, err := client.ListNodesAt(ctx, fs, scope, letfsclient.Locator{Path: &root, RootID: &box.ID}, 100, nil)
	require.NoError(t, err)
	require.Len(t, listed.Items, 2)
	preview, err := client.ReadImage(ctx, fs, scope, letfsclient.Locator{NodeID: &imageNode.ID, RootID: &box.ID}, nil)
	require.NoError(t, err)
	require.EqualValues(t, 2, preview.Width)
	require.EqualValues(t, 1, preview.Height)
	digest := sha256.Sum256(preview.Content)
	require.Equal(t, hex.EncodeToString(digest[:]), preview.SHA256)
	_, err = png.Decode(bytes.NewReader(preview.Content))
	require.NoError(t, err)
	_, err = client.Stat(ctx, fs, scope, letfsclient.Locator{NodeID: scopes[0].RootID, RootID: &box.ID}, true)
	require.Error(t, err)
	_, err = api.ReadText(ctx, &letfsv1.ReadTextRequest{FilesystemId: fs.String(), ScopeId: scope.String(), Locator: &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: text.ID.String()}}})
	require.Equal(t, codes.InvalidArgument, status.Code(err))
	_, err = api.GetDownload(ctx, &letfsv1.GetDownloadRequest{FilesystemId: fs.String(), ScopeId: scope.String(), NodeId: imageNode.ID.String()})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	_, err = api.CreateUpload(ctx, &letfsv1.CreateUploadRequest{})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	_, err = api.PurgeTrash(ctx, &letfsv1.PurgeTrashRequest{})
	require.Equal(t, codes.PermissionDenied, status.Code(err))
	noActor := metadata.NewOutgoingContext(t.Context(), metadata.Pairs("authorization", "Bearer "+token))
	_, err = client.Stat(noActor, fs, scope, loc, true)
	require.Error(t, err)
	stableID := uuid.Must(uuid.NewV7())
	creation := letfsclient.NodeCreation{NodeID: &stableID, Parent: letfsclient.Locator{NodeID: &box.ID, RootID: &box.ID}, Name: "home"}
	key := uuid.New()
	created, err := client.CreateNode(ctx, fs, scope, key, creation)
	require.NoError(t, err)
	require.Equal(t, stableID, created.ID)
	created, err = client.CreateNode(ctx, fs, scope, key, creation)
	require.NoError(t, err)
	require.Equal(t, stableID, created.ID)
	// Native writes retain the mount restriction through typed clients and direct RPCs.
	loc.ExpectedNodeID = &text.ID
	observed := letfsclient.TextTarget{Locator: loc, Revision: stat.Node.Revision, Fingerprint: &stat.Fingerprint}
	changed, err := client.WriteText(ctx, fs, scope, observed, []byte("new\n"))
	require.NoError(t, err)
	require.Equal(t, stat.Fingerprint, changed.BeforeFingerprint)
	observed.Revision = changed.Stat.Node.Revision
	observed.Fingerprint = &changed.Stat.Fingerprint
	loseAppendResponse.Store(true)
	_, err = client.AppendText(ctx, fs, scope, observed, []byte("once"))
	require.Error(t, err)
	_, err = client.AppendText(ctx, fs, scope, observed, []byte("once"))
	require.Error(t, err, "the old guard must not repeat a committed append after lost response")
	read, err := client.ReadText(ctx, fs, scope, loc, letfsclient.TextSelection{Kind: "whole"}, nil)
	require.NoError(t, err)
	require.Equal(t, []byte("new\nonce"), read.Content)
	observed.Revision = read.Stat.Node.Revision
	observed.Fingerprint = &read.Stat.Fingerprint
	old := "once"
	changed, err = client.PatchText(ctx, fs, scope, observed, letfsclient.TextPatch{OldText: &old, Content: []byte("twice")})
	require.NoError(t, err)
	observed.Revision = changed.Stat.Node.Revision
	observed.Fingerprint = &changed.Stat.Fingerprint
	offset := int64(0)
	changed, err = client.PatchText(ctx, fs, scope, observed, letfsclient.TextPatch{Offset: &offset, Content: []byte("NEW")})
	require.NoError(t, err)
	observed.Revision = changed.Stat.Node.Revision
	observed.Fingerprint = &changed.Stat.Fingerprint
	changed, err = client.TruncateText(ctx, fs, scope, observed, 4, true)
	require.NoError(t, err)
	require.EqualValues(t, 4, changed.Stat.ReadableSize)
	newID := uuid.Must(uuid.NewV7())
	newFile := letfsclient.TextTarget{Create: &letfsclient.TextCreation{Key: uuid.New(), Parent: letfsclient.Locator{NodeID: &box.ID, RootID: &box.ID}, Name: "created.txt", MediaType: "text/plain", NodeID: &newID}}
	changed, err = client.AppendText(ctx, fs, scope, newFile, []byte("created"))
	require.NoError(t, err)
	require.Zero(t, changed.BeforeRevision)
	require.Equal(t, newID, changed.Stat.Node.ID)
	_, err = api.WriteText(ctx, &letfsv1.WriteTextRequest{FilesystemId: fs.String(), ScopeId: scope.String()})
	require.Equal(t, codes.InvalidArgument, status.Code(err))
	_, err = client.WriteText(ctx, fs, scope, letfsclient.TextTarget{Locator: letfsclient.Locator{NodeID: &imageNode.ID, RootID: &box.ID}, Revision: imageNode.Revision}, []byte("edit"))
	require.Error(t, err, "Leta cannot replace blob bytes through the text API")
	_, err = client.CreateDirectories(ctx, fs, scope, letfsclient.Locator{NodeID: scopes[0].RootID, RootID: &box.ID}, []string{"escaped"}, false)
	require.Error(t, err)
	nested, err := client.CreateDirectories(ctx, fs, scope, letfsclient.Locator{Path: &root, RootID: &box.ID, ExpectedParentID: &box.ID}, []string{"nested", "leaf"}, true)
	require.NoError(t, err)
	entry, err := client.TrashNode(ctx, fs, scope, letfsclient.Locator{NodeID: &nested.ID, RootID: &box.ID}, &nested.Revision, true)
	require.NoError(t, err)
	require.Equal(t, nested.ID, entry.NodeID)
	_, err = client.WriteText(ctx, fs, scope, letfsclient.TextTarget{Locator: letfsclient.Locator{NodeID: &text.ID, RootID: &stableID}, Revision: changed.Stat.Node.Revision}, []byte("escape"))
	require.Error(t, err)
	// A generated child may be copied out, but cannot serve as a write destination or an independent root.
	artifact := uuid.Must(uuid.NewV7())
	_, err = db.Exec(actor, `INSERT INTO nodes(id,scope_id,parent_id,name,kind,size_bytes) VALUES($1,$2,$3,'artifact.txt','file',4)`, artifact, scope, imageNode.ID)
	require.NoError(t, err)
	_, err = db.Exec(actor, `INSERT INTO files(node_id,storage_kind,inline_bytes,media_type) VALUES($1,'inline','data','text/plain')`, artifact)
	require.NoError(t, err)
	_, err = db.Exec(actor, `UPDATE filesystems SET used_bytes=used_bytes+4,node_count=node_count+1 WHERE id=$1`, fs)
	require.NoError(t, err)
	_, err = client.WriteText(ctx, fs, scope, letfsclient.TextTarget{Locator: letfsclient.Locator{NodeID: &artifact, RootID: &box.ID}, Revision: 1}, []byte("no"))
	require.Error(t, err)
	boxID := box.ID.String()
	artifactRevision := int64(1)
	copyInput := &letfsv1.CreateCopyRequest{FilesystemId: fs.String(), ScopeId: scope.String(), SourceId: artifact.String(), ParentId: boxID, Name: "artifact-copy.txt", Revision: &artifactRevision, IdempotencyKey: uuid.NewString(), SourceRootId: &boxID, DestinationRootId: &boxID}
	copied, err := api.CreateCopy(ctx, copyInput)
	require.NoError(t, err)
	require.False(t, copied.Node.Readonly)
	copyInput.IdempotencyKey = uuid.NewString()
	copyInput.Name = "escape.txt"
	copyInput.ParentId = scopes[0].RootID.String()
	_, err = api.CreateCopy(ctx, copyInput)
	require.Equal(t, codes.NotFound, status.Code(err))
	copyInput.IdempotencyKey = uuid.NewString()
	copyInput.ParentId = artifact.String()
	_, err = api.CreateCopy(ctx, copyInput)
	require.Equal(t, codes.PermissionDenied, status.Code(err))
}
