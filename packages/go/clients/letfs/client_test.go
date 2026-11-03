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
	create   func(context.Context, *letfsv1.CreateStorageRequest) (*letfsv1.CreateStorageResponse, error)
	freeze   func(context.Context, *letfsv1.FreezeBucketRequest) (*letfsv1.FreezeBucketResponse, error)
	list     func(context.Context, *letfsv1.ListBucketFilesystemsRequest) (*letfsv1.ListBucketFilesystemsResponse, error)
	delete   func(context.Context, *letfsv1.DeleteFilesystemRequest) (*letfsv1.DeleteFilesystemResponse, error)
	complete func(context.Context, *letfsv1.CompleteBucketDeletionRequest) (*letfsv1.CompleteBucketDeletionResponse, error)
}

type fakeFilesystem struct {
	letfsv1.FilesystemServiceClient
	filesystem func(context.Context, *letfsv1.GetFilesystemRequest) (*letfsv1.GetFilesystemResponse, error)
	usage      func(context.Context, *letfsv1.GetBucketUsageRequest) (*letfsv1.GetBucketUsageResponse, error)
	node       func(context.Context, *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error)
	list       func(context.Context, *letfsv1.ListNodesRequest) (*letfsv1.ListNodesResponse, error)
	upload     func(context.Context, *letfsv1.CreateUploadRequest) (*letfsv1.CreateUploadResponse, error)
	trash      func(context.Context, *letfsv1.TrashNodeRequest) (*letfsv1.TrashNodeResponse, error)
	archive    func(context.Context, *letfsv1.StreamArchiveRequest) (grpc.ServerStreamingClient[letfsv1.StreamArchiveResponse], error)
}

func (f fakeFilesystem) GetFilesystem(ctx context.Context, in *letfsv1.GetFilesystemRequest, _ ...grpc.CallOption) (*letfsv1.GetFilesystemResponse, error) {
	return f.filesystem(ctx, in)
}
func (f fakeFilesystem) GetBucketUsage(ctx context.Context, in *letfsv1.GetBucketUsageRequest, _ ...grpc.CallOption) (*letfsv1.GetBucketUsageResponse, error) {
	return f.usage(ctx, in)
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

func (f fakeAdministration) CreateStorage(ctx context.Context, request *letfsv1.CreateStorageRequest, _ ...grpc.CallOption) (*letfsv1.CreateStorageResponse, error) {
	return f.create(ctx, request)
}
func (f fakeAdministration) FreezeBucket(ctx context.Context, request *letfsv1.FreezeBucketRequest, _ ...grpc.CallOption) (*letfsv1.FreezeBucketResponse, error) {
	return f.freeze(ctx, request)
}
func (f fakeAdministration) ListBucketFilesystems(ctx context.Context, request *letfsv1.ListBucketFilesystemsRequest, _ ...grpc.CallOption) (*letfsv1.ListBucketFilesystemsResponse, error) {
	return f.list(ctx, request)
}
func (f fakeAdministration) DeleteFilesystem(ctx context.Context, request *letfsv1.DeleteFilesystemRequest, _ ...grpc.CallOption) (*letfsv1.DeleteFilesystemResponse, error) {
	return f.delete(ctx, request)
}
func (f fakeAdministration) CompleteBucketDeletion(ctx context.Context, request *letfsv1.CompleteBucketDeletionRequest, _ ...grpc.CallOption) (*letfsv1.CompleteBucketDeletionResponse, error) {
	return f.complete(ctx, request)
}

func TestCreateStorageConvertsNativeContractAndValidatesScope(t *testing.T) {
	bucket, filesystem, root := uuid.New(), uuid.New(), uuid.New()
	input := Storage{LimitBytes: 1024, BucketID: bucket, FilesystemID: filesystem}
	client := Client{API: fakeAdministration{create: func(_ context.Context, request *letfsv1.CreateStorageRequest) (*letfsv1.CreateStorageResponse, error) {
		require.Equal(t, bucket.String(), request.GetBucket().GetIdempotencyKey())
		require.Equal(t, int64(1024), request.GetBucket().GetLimitBytes())
		require.Equal(t, filesystem.String(), request.GetFilesystem().GetIdempotencyKey())
		require.Equal(t, "drive", request.GetFilesystem().GetRootName())
		return &letfsv1.CreateStorageResponse{
			Bucket:     &letfsv1.Bucket{Id: bucket.String(), LimitBytes: 1024, State: "active"},
			Filesystem: &letfsv1.Filesystem{Id: filesystem.String(), BucketId: bucket.String(), RootId: root.String(), State: "active"},
		}, nil
	}}}
	result, err := client.CreateStorage(t.Context(), input)
	require.NoError(t, err)
	require.Equal(t, root, result.RootID)

	client.API = fakeAdministration{create: func(context.Context, *letfsv1.CreateStorageRequest) (*letfsv1.CreateStorageResponse, error) {
		return &letfsv1.CreateStorageResponse{Bucket: &letfsv1.Bucket{Id: uuid.NewString(), LimitBytes: 1024, State: "active"}, Filesystem: &letfsv1.Filesystem{Id: filesystem.String(), BucketId: bucket.String(), RootId: root.String(), State: "active"}}, nil
	}}
	_, err = client.CreateStorage(t.Context(), input)
	require.Equal(t, apperr.Conflict, apperr.KindOf(err))
}

func TestDeletionOperationsValidateOwnerResultsAndProgress(t *testing.T) {
	bucket, first, second := uuid.New(), uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	if first.String() > second.String() {
		first, second = second, first
	}
	client := Client{API: fakeAdministration{
		freeze: func(context.Context, *letfsv1.FreezeBucketRequest) (*letfsv1.FreezeBucketResponse, error) {
			return &letfsv1.FreezeBucketResponse{Bucket: &letfsv1.Bucket{Id: bucket.String(), State: "frozen"}}, nil
		},
		list: func(_ context.Context, request *letfsv1.ListBucketFilesystemsRequest) (*letfsv1.ListBucketFilesystemsResponse, error) {
			require.Equal(t, bucket.String(), request.GetBucketId())
			return &letfsv1.ListBucketFilesystemsResponse{FilesystemIds: []string{first.String(), second.String()}}, nil
		},
		delete: func(context.Context, *letfsv1.DeleteFilesystemRequest) (*letfsv1.DeleteFilesystemResponse, error) {
			return &letfsv1.DeleteFilesystemResponse{Completed: false}, nil
		},
		complete: func(context.Context, *letfsv1.CompleteBucketDeletionRequest) (*letfsv1.CompleteBucketDeletionResponse, error) {
			return &letfsv1.CompleteBucketDeletionResponse{Bucket: &letfsv1.Bucket{Id: bucket.String(), State: "deleted"}}, nil
		},
	}}
	require.NoError(t, client.FreezeBucket(t.Context(), bucket))
	ids, err := client.ListFilesystems(t.Context(), bucket, uuid.Nil)
	require.NoError(t, err)
	require.Equal(t, []uuid.UUID{first, second}, ids)
	completed, err := client.DeleteFilesystem(t.Context(), first)
	require.NoError(t, err)
	require.False(t, completed)
	require.NoError(t, client.CompleteBucket(t.Context(), bucket))
}

func TestListFilesystemsRejectsUnorderedOrOversizedPages(t *testing.T) {
	bucket, id := uuid.New(), uuid.New()
	for _, values := range [][]string{{id.String(), id.String()}, make([]string, 101)} {
		client := Client{API: fakeAdministration{list: func(context.Context, *letfsv1.ListBucketFilesystemsRequest) (*letfsv1.ListBucketFilesystemsResponse, error) {
			return &letfsv1.ListBucketFilesystemsResponse{FilesystemIds: values}, nil
		}}}
		_, err := client.ListFilesystems(t.Context(), bucket, uuid.Nil)
		require.Equal(t, apperr.Conflict, apperr.KindOf(err))
	}
}

func TestFilesystemReadsConvertAndValidateScope(t *testing.T) {
	filesystem, bucket, root, node, parent := uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New()
	paths := PathContext{Mounts: []Mount{{Path: "/", FilesystemID: filesystem}}}
	now := time.Now().UTC().Truncate(time.Second)
	native := &letfsv1.Node{Id: node.String(), FilesystemId: filesystem.String(), ParentId: pointer(parent.String()), Name: "report.pdf", Kind: "file", Revision: 3, SizeBytes: 42, CreatedAt: timestamppb.New(now), UpdatedAt: timestamppb.New(now)}
	api := fakeFilesystem{
		filesystem: func(_ context.Context, in *letfsv1.GetFilesystemRequest) (*letfsv1.GetFilesystemResponse, error) {
			require.Equal(t, filesystem.String(), in.GetFilesystemId())
			return &letfsv1.GetFilesystemResponse{Filesystem: &letfsv1.Filesystem{Id: filesystem.String(), BucketId: bucket.String(), RootId: root.String(), State: "active"}}, nil
		},
		usage: func(_ context.Context, in *letfsv1.GetBucketUsageRequest) (*letfsv1.GetBucketUsageResponse, error) {
			require.Equal(t, bucket.String(), in.GetBucketId())
			return &letfsv1.GetBucketUsageResponse{Bucket: &letfsv1.Bucket{Id: bucket.String(), LimitBytes: 100, UsedBytes: 42, State: "active"}, UploadLimits: &letfsv1.UploadLimits{InlineLimitBytes: 10, MaxFileBytes: 90}}, nil
		},
		node: func(_ context.Context, in *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error) {
			require.Equal(t, node.String(), in.GetNodeId())
			require.Equal(t, filesystem.String(), in.GetPathContext().GetMounts()[0].GetFilesystemId())
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
	require.Equal(t, root, fs.RootID)
	usage, err := client.GetBucketUsage(t.Context(), bucket)
	require.NoError(t, err)
	require.Equal(t, int64(42), usage.UsedBytes)
	item, err := client.GetNode(t.Context(), filesystem, node, paths)
	require.NoError(t, err)
	require.Equal(t, &parent, item.ParentID)
	require.Equal(t, now, item.CreatedAt)
	page, err := client.ListNodes(t.Context(), filesystem, parent, paths, 20, nil)
	require.NoError(t, err)
	require.Len(t, page.Items, 1)
	require.Equal(t, "next", *page.NextCursor)
}

func TestFilesystemReadsRejectForeignObjects(t *testing.T) {
	filesystem, node := uuid.New(), uuid.New()
	client := FilesystemClient{API: fakeFilesystem{node: func(context.Context, *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error) {
		return &letfsv1.GetNodeResponse{Node: &letfsv1.Node{Id: node.String(), FilesystemId: uuid.NewString()}}, nil
	}}}
	_, err := client.GetNode(t.Context(), filesystem, node, PathContext{Mounts: []Mount{{Path: "/", FilesystemID: filesystem}}})
	require.Equal(t, apperr.Conflict, apperr.KindOf(err))
}

func pointer[T any](value T) *T { return &value }

func TestMutationRequestsCarryPathContextAndNativeTargets(t *testing.T) {
	filesystem, parent, node, key, entry := uuid.New(), uuid.New(), uuid.New(), uuid.New(), uuid.New()
	paths := PathContext{Mounts: []Mount{{Path: "/", FilesystemID: filesystem}}}
	api := fakeFilesystem{
		upload: func(_ context.Context, in *letfsv1.CreateUploadRequest) (*letfsv1.CreateUploadResponse, error) {
			require.Equal(t, filesystem.String(), in.GetPathContext().GetMounts()[0].GetFilesystemId())
			require.Equal(t, parent.String(), in.GetDestination().GetParent().GetNodeId())
			return &letfsv1.CreateUploadResponse{Upload: &letfsv1.Upload{Id: key.String(), Status: "pending", Transport: "object"}}, nil
		},
		trash: func(_ context.Context, in *letfsv1.TrashNodeRequest) (*letfsv1.TrashNodeResponse, error) {
			require.Equal(t, node.String(), in.GetLocator().GetNodeId())
			return &letfsv1.TrashNodeResponse{Entry: &letfsv1.TrashEntry{Id: entry.String(), NodeId: node.String(), ActorId: uuid.NewString(), Name: "x", Status: "trashed"}}, nil
		},
	}
	client := FilesystemClient{API: api}
	upload, err := client.CreateUpload(t.Context(), filesystem, key, parent, paths, "x", "text/plain", nil, nil)
	require.NoError(t, err)
	require.Equal(t, key, upload.ID)
	trashed, err := client.Trash(t.Context(), filesystem, node, paths, nil)
	require.NoError(t, err)
	require.Equal(t, entry, trashed.ID)
}

func TestArchiveStreamConvertsFramesAndErrors(t *testing.T) {
	filesystem, node := uuid.New(), uuid.New()
	paths := PathContext{Mounts: []Mount{{Path: "/", FilesystemID: filesystem}}}
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
	archive, err := client.StreamArchive(t.Context(), filesystem, node, paths)
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
