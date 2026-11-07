package letfs

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/stretchr/testify/require"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type fakeAdministration struct {
	letfsv1.StorageAdministrationServiceClient
	createFilesystem func(context.Context, *letfsv1.CreateFilesystemRequest) (*letfsv1.CreateFilesystemResponse, error)
	createScopes     func(context.Context, *letfsv1.CreateScopesRequest) (*letfsv1.CreateScopesResponse, error)
	delete           func(context.Context, *letfsv1.DeleteFilesystemRequest) (*letfsv1.DeleteFilesystemResponse, error)
}

type fakeFilesystem struct {
	semantic func(context.Context, *letfsv1.SemanticSearchRequest) (*letfsv1.SemanticSearchResponse, error)
	letfsv1.FilesystemServiceClient
	filesystem func(context.Context, *letfsv1.GetFilesystemRequest) (*letfsv1.GetFilesystemResponse, error)
	node       func(context.Context, *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error)
	list       func(context.Context, *letfsv1.ListNodesRequest) (*letfsv1.ListNodesResponse, error)
	upload     func(context.Context, *letfsv1.CreateUploadRequest) (*letfsv1.CreateUploadResponse, error)
	trash      func(context.Context, *letfsv1.TrashNodeRequest) (*letfsv1.TrashNodeResponse, error)
	archive    func(context.Context, *letfsv1.StreamArchiveRequest) (grpc.ServerStreamingClient[letfsv1.StreamArchiveResponse], error)
}

func (f fakeFilesystem) GetFilesystem(ctx context.Context, in *letfsv1.GetFilesystemRequest, _ ...grpc.CallOption) (*letfsv1.GetFilesystemResponse, error) {
	return f.filesystem(ctx, in)
}
func (f fakeFilesystem) GetNode(ctx context.Context, in *letfsv1.GetNodeRequest, _ ...grpc.CallOption) (*letfsv1.GetNodeResponse, error) {
	return f.node(ctx, in)
}
func (f fakeFilesystem) ListNodes(ctx context.Context, in *letfsv1.ListNodesRequest, _ ...grpc.CallOption) (*letfsv1.ListNodesResponse, error) {
	return f.list(ctx, in)
}
func (f fakeFilesystem) CreateUpload(ctx context.Context, in *letfsv1.CreateUploadRequest, _ ...grpc.CallOption) (*letfsv1.CreateUploadResponse, error) {
	return f.upload(ctx, in)
}
func (f fakeFilesystem) TrashNode(ctx context.Context, in *letfsv1.TrashNodeRequest, _ ...grpc.CallOption) (*letfsv1.TrashNodeResponse, error) {
	return f.trash(ctx, in)
}
func (f fakeFilesystem) StreamArchive(ctx context.Context, in *letfsv1.StreamArchiveRequest, _ ...grpc.CallOption) (grpc.ServerStreamingClient[letfsv1.StreamArchiveResponse], error) {
	return f.archive(ctx, in)
}

type fakeArchive struct {
	grpc.ServerStreamingClient[letfsv1.StreamArchiveResponse]
	recv func() (*letfsv1.StreamArchiveResponse, error)
}

func (f fakeArchive) Recv() (*letfsv1.StreamArchiveResponse, error) { return f.recv() }

func (f fakeAdministration) CreateFilesystem(ctx context.Context, request *letfsv1.CreateFilesystemRequest, _ ...grpc.CallOption) (*letfsv1.CreateFilesystemResponse, error) {
	return f.createFilesystem(ctx, request)
}
func (f fakeAdministration) DeleteFilesystem(ctx context.Context, request *letfsv1.DeleteFilesystemRequest, _ ...grpc.CallOption) (*letfsv1.DeleteFilesystemResponse, error) {
	return f.delete(ctx, request)
}

func TestCreateFilesystemValidatesIdentityAndQuota(t *testing.T) {
	id, key := uuid.New(), uuid.New()
	value := &letfsv1.Filesystem{Id: id.String(), LimitBytes: 1024, State: "active"}
	c := Client{API: fakeAdministration{createFilesystem: func(_ context.Context, in *letfsv1.CreateFilesystemRequest) (*letfsv1.CreateFilesystemResponse, error) {
		require.Equal(t, key.String(), in.IdempotencyKey)
		require.EqualValues(t, 1024, in.LimitBytes)
		return &letfsv1.CreateFilesystemResponse{Filesystem: value}, nil
	}}}
	got, err := c.CreateFilesystem(t.Context(), id, key, 1024)
	require.NoError(t, err)
	require.Equal(t, id, got.ID)
	value.LimitBytes++
	_, err = c.CreateFilesystem(t.Context(), id, key, 1024)
	require.Equal(t, apperr.Conflict, apperr.KindOf(err))
}
func TestCreateScopesValidatesOptions(t *testing.T) {
	fs, id, key := uuid.New(), uuid.New(), uuid.New()
	for _, blob := range []bool{false, true} {
		for _, index := range []bool{false, true} {
			value := &letfsv1.Scope{Id: id.String(), FilesystemId: fs.String(), RootId: uuid.NewString(), State: "active", AllowBlobFiles: blob, AllowIndexing: index}
			c := Client{API: fakeAdministration{createScopes: func(_ context.Context, in *letfsv1.CreateScopesRequest) (*letfsv1.CreateScopesResponse, error) {
				require.NotNil(t, in.AllowBlobFiles)
				require.NotNil(t, in.AllowIndexing)
				require.Equal(t, blob, in.GetAllowBlobFiles())
				require.Equal(t, index, in.GetAllowIndexing())
				return &letfsv1.CreateScopesResponse{Scopes: []*letfsv1.Scope{value}}, nil
			}}}
			got, err := c.CreateScopes(t.Context(), fs, key, []uuid.UUID{id}, blob, index)
			require.NoError(t, err)
			require.Equal(t, blob, got[0].AllowBlobFiles)
			require.Equal(t, index, got[0].AllowIndexing)
			value.AllowIndexing = !index
			_, err = c.CreateScopes(t.Context(), fs, key, []uuid.UUID{id}, blob, index)
			require.Equal(t, apperr.Conflict, apperr.KindOf(err))
		}
	}
}

func TestFilesystemReadsConvertAndValidateScope(t *testing.T) {
	filesystem, scope, node, parent := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	now := time.Now().UTC().Truncate(time.Second)
	native := &letfsv1.Node{Id: node.String(), ScopeId: scope.String(), ParentId: pointer(parent.String()), Name: "report.pdf", Kind: "file", Revision: 3, SizeBytes: 42, CreatedAt: timestamppb.New(now), UpdatedAt: timestamppb.New(now)}
	api := fakeFilesystem{
		filesystem: func(_ context.Context, in *letfsv1.GetFilesystemRequest) (*letfsv1.GetFilesystemResponse, error) {
			require.Equal(t, filesystem.String(), in.GetFilesystemId())
			return &letfsv1.GetFilesystemResponse{Filesystem: &letfsv1.Filesystem{Id: filesystem.String(), LimitBytes: 100, UsedBytes: 42, State: "active"}}, nil
		},
		node: func(_ context.Context, in *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error) {
			require.Equal(t, node.String(), in.GetNodeId())
			require.Equal(t, filesystem.String(), in.GetFilesystemId())
			return &letfsv1.GetNodeResponse{Node: native}, nil
		},
		list: func(_ context.Context, in *letfsv1.ListNodesRequest) (*letfsv1.ListNodesResponse, error) {
			require.Equal(t, parent.String(), in.GetParent().GetNodeId())
			return &letfsv1.ListNodesResponse{Items: []*letfsv1.Node{native}, NextCursor: pointer("next")}, nil
		},
	}
	client := FilesystemClient{API: api}
	fs, err := client.GetFilesystem(t.Context(), filesystem)
	require.NoError(t, err)
	require.EqualValues(t, 42, fs.UsedBytes)
	item, err := client.GetNode(t.Context(), filesystem, scope, node)
	require.NoError(t, err)
	require.Equal(t, &parent, item.ParentID)
	require.Equal(t, now, item.CreatedAt)
	page, err := client.ListNodes(t.Context(), filesystem, scope, parent, 20, nil)
	require.NoError(t, err)
	require.Len(t, page.Items, 1)
	require.Equal(t, "next", *page.NextCursor)
}

func TestFilesystemReadsRejectForeignObjects(t *testing.T) {
	filesystem, scope, node := uuid.New(), uuid.New(), uuid.New()
	client := FilesystemClient{API: fakeFilesystem{node: func(context.Context, *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error) {
		return &letfsv1.GetNodeResponse{Node: &letfsv1.Node{Id: node.String(), ScopeId: uuid.NewString()}}, nil
	}}}
	_, err := client.GetNode(t.Context(), filesystem, scope, node)
	require.Equal(t, apperr.Conflict, apperr.KindOf(err))
}

func pointer[T any](value T) *T { return &value }

func TestMutationRequestsCarryScopeAndNativeTargets(t *testing.T) {
	filesystem, scope, parent, node, key, entry := uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New()
	api := fakeFilesystem{
		upload: func(_ context.Context, in *letfsv1.CreateUploadRequest) (*letfsv1.CreateUploadResponse, error) {
			require.Equal(t, filesystem.String(), in.GetFilesystemId())
			require.Equal(t, parent.String(), in.GetDestination().GetParent().GetNodeId())
			return &letfsv1.CreateUploadResponse{Upload: &letfsv1.Upload{Id: key.String(), Status: "pending", Transport: "object"}}, nil
		},
		trash: func(_ context.Context, in *letfsv1.TrashNodeRequest) (*letfsv1.TrashNodeResponse, error) {
			require.Equal(t, node.String(), in.GetLocator().GetNodeId())
			return &letfsv1.TrashNodeResponse{Entry: &letfsv1.TrashEntry{Id: entry.String(), NodeId: node.String(), ActorId: uuid.NewString(), Name: "x", Status: "trashed"}}, nil
		},
	}
	client := FilesystemClient{API: api}
	upload, err := client.CreateUpload(t.Context(), filesystem, scope, key, parent, "x", "text/plain", nil, nil)
	require.NoError(t, err)
	require.Equal(t, key, upload.ID)
	trashed, err := client.Trash(t.Context(), filesystem, scope, node, nil)
	require.NoError(t, err)
	require.Equal(t, entry, trashed.ID)
}

func TestArchiveStreamConvertsFramesAndErrors(t *testing.T) {
	filesystem, scope, node := uuid.New(), uuid.New(), uuid.New()
	calls := 0
	stream := fakeArchive{recv: func() (*letfsv1.StreamArchiveResponse, error) {
		calls++
		if calls == 1 {
			return &letfsv1.StreamArchiveResponse{Frame: &letfsv1.StreamArchiveResponse_Metadata{Metadata: &letfsv1.ArchiveMetadata{Filename: "files.zip", Mime: "application/zip"}}}, nil
		}
		if calls == 2 {
			return &letfsv1.StreamArchiveResponse{Frame: &letfsv1.StreamArchiveResponse_Data{Data: []byte("zip")}}, nil
		}
		return nil, context.Canceled
	}}
	client := FilesystemClient{API: fakeFilesystem{archive: func(_ context.Context, in *letfsv1.StreamArchiveRequest) (grpc.ServerStreamingClient[letfsv1.StreamArchiveResponse], error) {
		require.Equal(t, node.String(), in.GetNodeId())
		return stream, nil
	}}}
	archive, err := client.StreamArchive(t.Context(), filesystem, scope, node)
	require.NoError(t, err)
	metadata, err := archive.Recv()
	require.NoError(t, err)
	require.Equal(t, "files.zip", metadata.Filename)
	data, err := archive.Recv()
	require.NoError(t, err)
	require.Equal(t, []byte("zip"), data.Data)
	_, err = archive.Recv()
	require.Equal(t, apperr.Canceled, apperr.KindOf(err))
}

func TestArchiveCloseCancelsEarlyReader(t *testing.T) {
	ctx, cancel := context.WithCancel(t.Context())
	stream := &ArchiveStream{cancel: cancel}
	stream.Close()
	select {
	case <-ctx.Done():
	default:
		t.Fatal("archive close did not cancel stream")
	}
	stream.Close()
}

func (f fakeAdministration) CreateScopes(ctx context.Context, in *letfsv1.CreateScopesRequest, _ ...grpc.CallOption) (*letfsv1.CreateScopesResponse, error) {
	return f.createScopes(ctx, in)
}
func TestCreateScopesRejectsMalformedAndForeignResults(t *testing.T) {
	fs, key, a, b, root := uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New()
	valid := func(id uuid.UUID) *letfsv1.Scope {
		return &letfsv1.Scope{Id: id.String(), FilesystemId: fs.String(), RootId: root.String(), State: "active", AllowBlobFiles: true, AllowIndexing: true}
	}
	for name, scopes := range map[string][]*letfsv1.Scope{
		"missing": {valid(a)}, "duplicate": {valid(a), valid(a)}, "foreign": {valid(a), valid(uuid.New())},
		"foreign filesystem": {valid(a), {Id: b.String(), FilesystemId: uuid.NewString(), RootId: root.String(), State: "active", AllowBlobFiles: true, AllowIndexing: true}},
		"invalid root":       {valid(a), {Id: b.String(), FilesystemId: fs.String(), RootId: "invalid", State: "active"}},
		"nil":                {valid(a), nil},
	} {
		t.Run(name, func(t *testing.T) {
			c := Client{API: fakeAdministration{createScopes: func(_ context.Context, in *letfsv1.CreateScopesRequest) (*letfsv1.CreateScopesResponse, error) {
				require.Equal(t, fs.String(), in.FilesystemId)
				require.Equal(t, key.String(), in.IdempotencyKey)
				return &letfsv1.CreateScopesResponse{Scopes: scopes}, nil
			}}}
			_, err := c.CreateScopes(t.Context(), fs, key, []uuid.UUID{a, b}, true, true)
			require.Error(t, err)
		})
	}
}

func (f fakeFilesystem) SemanticSearch(ctx context.Context, in *letfsv1.SemanticSearchRequest, _ ...grpc.CallOption) (*letfsv1.SemanticSearchResponse, error) {
	return f.semantic(ctx, in)
}

func TestSemanticSearchBoundsOutputAndChecksReturnedScope(t *testing.T) {
	fs, scope, file := uuid.New(), uuid.New(), uuid.New()
	node := &letfsv1.Node{Id: file.String(), ScopeId: scope.String()}
	client := FilesystemClient{API: fakeFilesystem{semantic: func(_ context.Context, in *letfsv1.SemanticSearchRequest) (*letfsv1.SemanticSearchResponse, error) {
		require.Equal(t, fs.String(), in.FilesystemId)
		require.Equal(t, scope.String(), in.ScopeId)
		require.Equal(t, "report", in.Query)
		require.EqualValues(t, 1, in.GetLimit())
		require.Nil(t, in.ProtoReflect().Descriptor().Fields().ByName("cursor"))
		return &letfsv1.SemanticSearchResponse{Items: []*letfsv1.SearchResult{{Node: node, Path: "/report"}}}, nil
	}}}
	result, err := client.SemanticSearch(t.Context(), fs, scope, "report", 1)
	require.NoError(t, err)
	require.Equal(t, file, result.Items[0].Node.ID)
	node.ScopeId = uuid.NewString()
	_, err = client.SemanticSearchWithOptions(t.Context(), fs, scope, SemanticSearchOptions{Query: "report", Limit: pointer(int32(1))})
	require.Equal(t, apperr.Conflict, apperr.KindOf(err))
}
