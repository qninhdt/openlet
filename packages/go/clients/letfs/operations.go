package letfs

import (
	"context"
	"io"
	"time"

	"github.com/google/uuid"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

type Download struct {
	MIME, Filename, ETag string
	SizeBytes            int64
	InlineContent        []byte
	SignedURL            string
}
type Processing struct {
	FileID            uuid.UUID
	DesiredGeneration int64
	PublicationStatus string
	ErrorCode         *string
}
type Reprocess struct {
	FileID     uuid.UUID
	Generation int64
	WorkflowID string
}
type TrashEntry struct {
	ID, NodeID, ActorID uuid.UUID
	ParentID            *uuid.UUID
	Name, Status        string
	CreatedAt           time.Time
}
type TrashPage struct {
	Items      []TrashEntry
	NextCursor *string
}
type SignedUpload struct {
	URL           string
	Headers       map[string]string
	ContentLength int64
	ExpiresAt     time.Time
}
type UploadReceipt struct {
	ID        uuid.UUID
	Status    string
	SizeBytes int64
}
type UploadPublication struct {
	NodeID   uuid.UUID
	Status   string
	Revision int64
}
type Upload struct {
	ID                uuid.UUID
	Status, Transport string
	ExpiresAt         time.Time
	SizeBytes         *int64
	PartSizeBytes     *int64
	PartCount         *int32
	Transfer          *SignedUpload
	Publication       *UploadPublication
	Receipt           *UploadReceipt
}
type UploadPart struct {
	Number   int32
	Transfer SignedUpload
}
type PartReceipt struct {
	Number int32
	ETag   string
}

func nativeTrash(value *letfsv1.TrashEntry, filesystem uuid.UUID) (TrashEntry, error) {
	if value == nil {
		return TrashEntry{}, scopeError()
	}
	id, err := parseID(value.GetId())
	if err != nil {
		return TrashEntry{}, err
	}
	node, err := parseID(value.GetNodeId())
	if err != nil {
		return TrashEntry{}, err
	}
	actor, err := parseID(value.GetActorId())
	if err != nil {
		return TrashEntry{}, err
	}
	out := TrashEntry{ID: id, NodeID: node, ActorID: actor, Name: value.GetName(), Status: value.GetStatus()}
	if value.ParentId != nil {
		parent, err := parseID(value.GetParentId())
		if err != nil {
			return TrashEntry{}, err
		}
		out.ParentID = &parent
	}
	if value.GetCreatedAt() != nil {
		out.CreatedAt = value.GetCreatedAt().AsTime()
	}
	return out, nil
}
func nativeSigned(value *letfsv1.SignedUpload) *SignedUpload {
	if value == nil {
		return nil
	}
	out := &SignedUpload{URL: value.GetUrl(), Headers: value.GetHeaders(), ContentLength: value.GetContentLength()}
	if value.GetExpiresAt() != nil {
		out.ExpiresAt = value.GetExpiresAt().AsTime()
	}
	return out
}
func nativeReceipt(value *letfsv1.UploadReceipt) (*UploadReceipt, error) {
	if value == nil {
		return nil, nil
	}
	id, err := parseID(value.GetId())
	if err != nil {
		return nil, err
	}
	return &UploadReceipt{ID: id, Status: value.GetStatus(), SizeBytes: value.GetSizeBytes()}, nil
}
func nativePublication(value *letfsv1.UploadPublication) (*UploadPublication, error) {
	if value == nil {
		return nil, nil
	}
	id, err := parseID(value.GetNodeId())
	if err != nil {
		return nil, err
	}
	return &UploadPublication{NodeID: id, Status: value.GetStatus(), Revision: value.GetRevision()}, nil
}
func nativeUpload(value *letfsv1.Upload) (Upload, error) {
	if value == nil {
		return Upload{}, scopeError()
	}
	id, err := parseID(value.GetId())
	if err != nil {
		return Upload{}, err
	}
	publication, err := nativePublication(value.GetPublication())
	if err != nil {
		return Upload{}, err
	}
	receipt, err := nativeReceipt(value.GetReceipt())
	if err != nil {
		return Upload{}, err
	}
	out := Upload{ID: id, Status: value.GetStatus(), Transport: value.GetTransport(), SizeBytes: value.SizeBytes, PartSizeBytes: value.PartSizeBytes, PartCount: value.PartCount, Transfer: nativeSigned(value.GetTransfer()), Publication: publication, Receipt: receipt}
	if value.GetExpiresAt() != nil {
		out.ExpiresAt = value.GetExpiresAt().AsTime()
	}
	return out, nil
}

func (c FilesystemClient) ReplaceContent(ctx context.Context, filesystem, scope, node uuid.UUID, revision *int64, content []byte, mediaType string) (Node, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ReplaceContent(ctx, &letfsv1.ReplaceContentRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), Locator: nodeLocator(node), Revision: revision, Content: content, MediaType: mediaType})
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	value, err := nativeNode(response.GetNode(), scope)
	if err != nil || value.ID != node {
		return Node{}, scopeError()
	}
	return value, nil
}
func (c FilesystemClient) CreateCopy(ctx context.Context, filesystem, scope, destinationScope, source, parent, key uuid.UUID, name string, revision *int64) (Node, error) {
	if destinationScope == uuid.Nil {
		destinationScope = scope
	}
	ctx, cancel := context.WithTimeout(ctx, 120*time.Second)
	defer cancel()
	response, err := c.API.CreateCopy(ctx, &letfsv1.CreateCopyRequest{DestinationScopeId: uuidString(&destinationScope), FilesystemId: filesystem.String(), ScopeId: scope.String(), SourceId: source.String(), ParentId: parent.String(), Name: name, Revision: revision, IdempotencyKey: key.String()})
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	return nativeNode(response.GetNode(), destinationScope)
}
func (c FilesystemClient) GetProcessing(ctx context.Context, filesystem, scope, node uuid.UUID) (Processing, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.GetProcessing(ctx, &letfsv1.GetProcessingRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), NodeId: node.String()})
	if err != nil {
		return Processing{}, rpc.DecodeError(err)
	}
	value := response.GetProcessing()
	id, err := parseID(value.GetFileId())
	if err != nil || id != node {
		return Processing{}, scopeError()
	}
	return Processing{FileID: id, DesiredGeneration: value.GetDesiredGeneration(), PublicationStatus: value.GetPublicationStatus(), ErrorCode: value.ErrorCode}, nil
}
func (c FilesystemClient) Reprocess(ctx context.Context, filesystem, scope, node, key uuid.UUID) (Reprocess, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ReprocessNode(ctx, &letfsv1.ReprocessNodeRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), NodeId: node.String(), IdempotencyKey: key.String()})
	if err != nil {
		return Reprocess{}, rpc.DecodeError(err)
	}
	id, err := parseID(response.GetFileId())
	if err != nil || id != node {
		return Reprocess{}, scopeError()
	}
	return Reprocess{FileID: id, Generation: response.GetGeneration(), WorkflowID: response.GetWorkflowId()}, nil
}
func (c FilesystemClient) Trash(ctx context.Context, filesystem, scope, node uuid.UUID, revision *int64) (TrashEntry, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.TrashNode(ctx, &letfsv1.TrashNodeRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), Locator: nodeLocator(node), Revision: revision})
	if err != nil {
		return TrashEntry{}, rpc.DecodeError(err)
	}
	return nativeTrash(response.GetEntry(), scope)
}
func (c FilesystemClient) ListTrash(ctx context.Context, filesystem, scope uuid.UUID, limit int32, cursor *string) (TrashPage, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ListTrash(ctx, &letfsv1.ListTrashRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), Limit: &limit, Cursor: cursor})
	if err != nil {
		return TrashPage{}, rpc.DecodeError(err)
	}
	items := make([]TrashEntry, len(response.GetItems()))
	for i, item := range response.GetItems() {
		items[i], err = nativeTrash(item, filesystem)
		if err != nil {
			return TrashPage{}, err
		}
	}
	return TrashPage{Items: items, NextCursor: response.NextCursor}, nil
}
func (c FilesystemClient) GetTrash(ctx context.Context, filesystem, scope, id uuid.UUID) (TrashEntry, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.GetTrash(ctx, &letfsv1.GetTrashRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), EntryId: id.String()})
	if err != nil {
		return TrashEntry{}, rpc.DecodeError(err)
	}
	value, err := nativeTrash(response.GetEntry(), scope)
	if err != nil || value.ID != id {
		return TrashEntry{}, scopeError()
	}
	return value, nil
}
func (c FilesystemClient) RestoreTrash(ctx context.Context, filesystem, scope, id uuid.UUID, destinationScope, parent *uuid.UUID, name *string) (Node, error) {
	request := &letfsv1.RestoreTrashRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), EntryId: id.String(), DestinationScopeId: uuidString(destinationScope), Name: name}
	if parent != nil {
		request.Parent = nodeLocator(*parent)
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.RestoreTrash(ctx, request)
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	expected := scope
	if destinationScope != nil {
		expected = *destinationScope
	}
	return nativeNode(response.GetNode(), expected)
}
func (c FilesystemClient) PurgeTrash(ctx context.Context, filesystem, scope, id uuid.UUID) error {
	ctx, cancel := context.WithTimeout(ctx, 120*time.Second)
	defer cancel()
	_, err := c.API.PurgeTrash(ctx, &letfsv1.PurgeTrashRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), EntryId: id.String()})
	return rpc.DecodeError(err)
}

func (c FilesystemClient) CreateUpload(ctx context.Context, filesystem, scope, key, parent uuid.UUID, name, mediaType string, size *int64, md5 *string) (Upload, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CreateUpload(ctx, &letfsv1.CreateUploadRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), IdempotencyKey: key.String(), SizeBytes: size, MediaType: mediaType, ContentMd5: md5, Target: &letfsv1.CreateUploadRequest_Destination{Destination: &letfsv1.UploadDestination{Parent: nodeLocator(parent), Name: name}}})
	if err != nil {
		return Upload{}, rpc.DecodeError(err)
	}
	return nativeUpload(response.GetUpload())
}
func (c FilesystemClient) CreateReplacementUpload(ctx context.Context, filesystem, scope, key, node uuid.UUID, revision *int64, mediaType string, size *int64, md5 *string) (Upload, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CreateUpload(ctx, &letfsv1.CreateUploadRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), IdempotencyKey: key.String(), SizeBytes: size, MediaType: mediaType, ContentMd5: md5, Target: &letfsv1.CreateUploadRequest_Replacement{Replacement: &letfsv1.UploadReplacement{Locator: nodeLocator(node), Revision: revision}}})
	if err != nil {
		return Upload{}, rpc.DecodeError(err)
	}
	return nativeUpload(response.GetUpload())
}
func (c FilesystemClient) GetUpload(ctx context.Context, filesystem, scope, id uuid.UUID) (Upload, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.GetUpload(ctx, &letfsv1.GetUploadRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), UploadId: id.String()})
	if err != nil {
		return Upload{}, rpc.DecodeError(err)
	}
	value, err := nativeUpload(response.GetUpload())
	if err != nil || value.ID != id {
		return Upload{}, scopeError()
	}
	return value, nil
}
func (c FilesystemClient) GetUploadParts(ctx context.Context, filesystem, scope, id uuid.UUID, numbers []int32) ([]UploadPart, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.GetUploadParts(ctx, &letfsv1.GetUploadPartsRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), UploadId: id.String(), Numbers: numbers})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	items := make([]UploadPart, len(response.GetItems()))
	for i, item := range response.GetItems() {
		if item.GetPartNumber() < 1 || item.GetTransfer() == nil {
			return nil, scopeError()
		}
		items[i] = UploadPart{Number: item.GetPartNumber(), Transfer: *nativeSigned(item.GetTransfer())}
	}
	return items, nil
}
func receipts(values []PartReceipt) []*letfsv1.PartReceipt {
	out := make([]*letfsv1.PartReceipt, len(values))
	for i, value := range values {
		out[i] = &letfsv1.PartReceipt{PartNumber: value.Number, Etag: value.ETag}
	}
	return out
}
func (c FilesystemClient) CompleteUpload(ctx context.Context, filesystem, scope, id uuid.UUID, parts []PartReceipt) (UploadPublication, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CompleteUpload(ctx, &letfsv1.CompleteUploadRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), UploadId: id.String(), Parts: receipts(parts)})
	if err != nil {
		return UploadPublication{}, rpc.DecodeError(err)
	}
	value, err := nativePublication(response.GetPublication())
	if err != nil || value == nil {
		return UploadPublication{}, scopeError()
	}
	return *value, nil
}
func (c FilesystemClient) AbortUpload(ctx context.Context, filesystem, scope, id uuid.UUID) error {
	ctx, cancel := bounded(ctx)
	defer cancel()
	_, err := c.API.AbortUpload(ctx, &letfsv1.AbortUploadRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), UploadId: id.String()})
	return rpc.DecodeError(err)
}
func (c FilesystemClient) GetDownload(ctx context.Context, filesystem, scope, node uuid.UUID, revision *int64) (Download, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.GetDownload(ctx, &letfsv1.GetDownloadRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), NodeId: node.String(), Revision: revision})
	if err != nil {
		return Download{}, rpc.DecodeError(err)
	}
	value := response.GetDownload()
	if value == nil {
		return Download{}, scopeError()
	}
	return Download{MIME: value.GetMime(), Filename: value.GetFilename(), ETag: value.GetEtag(), SizeBytes: value.GetSizeBytes(), InlineContent: value.GetInlineContent(), SignedURL: value.GetSignedUrl()}, nil
}

type ArchiveFrame struct {
	Filename, MIME string
	Data           []byte
}
type ArchiveStream struct {
	stream letfsv1.FilesystemService_StreamArchiveClient
	cancel context.CancelFunc
}

func (c FilesystemClient) StreamArchive(ctx context.Context, filesystem, scope, node uuid.UUID) (*ArchiveStream, error) {
	streamContext, cancel := context.WithCancel(ctx)
	stream, err := c.API.StreamArchive(streamContext, &letfsv1.StreamArchiveRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), NodeId: node.String()})
	if err != nil {
		cancel()
		return nil, rpc.DecodeError(err)
	}
	return &ArchiveStream{stream: stream, cancel: cancel}, nil
}

// Close cancels the underlying RPC when the caller stops reading before EOF.
func (s *ArchiveStream) Close() {
	if s.cancel != nil {
		s.cancel()
		s.cancel = nil
	}
}
func (s *ArchiveStream) Recv() (ArchiveFrame, error) {
	value, err := s.stream.Recv()
	if err != nil {
		s.Close()
		if err == io.EOF {
			return ArchiveFrame{}, io.EOF
		}
		return ArchiveFrame{}, rpc.DecodeError(err)
	}
	if metadata := value.GetMetadata(); metadata != nil {
		return ArchiveFrame{Filename: metadata.GetFilename(), MIME: metadata.GetMime()}, nil
	}
	data := value.GetData()
	if len(data) == 0 {
		return ArchiveFrame{}, scopeError()
	}
	return ArchiveFrame{Data: data}, nil
}
