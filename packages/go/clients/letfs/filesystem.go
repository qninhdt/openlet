package letfs

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type FilesystemClient struct {
	API letfsv1.FilesystemServiceClient
}

type Filesystem struct {
	ID, BucketID, RootID uuid.UUID
	State                string
}

type BucketUsage struct {
	ID                      uuid.UUID
	LimitBytes, UsedBytes   int64
	State                   string
	InlineLimitBytes        int64
	MaxFileBytes            int64
	MultipartThresholdBytes int64
	MultipartPartBytes      int64
}

type Node struct {
	ID, FilesystemID uuid.UUID
	ParentID         *uuid.UUID
	Name, Kind       string
	Revision         int64
	SizeBytes        int64
	MediaType        *string
	CreatedAt        time.Time
	UpdatedAt        time.Time
	Title            *string
	Description      *string
	SemanticType     *string
	Context          *string
}

type NodePage struct {
	Items      []Node
	NextCursor *string
}

type Mount struct {
	Path         string
	FilesystemID uuid.UUID
}
type PathContext struct{ Mounts []Mount }
type Locator struct {
	NodeID                                  *uuid.UUID
	Path                                    *string
	CwdID, ExpectedNodeID, ExpectedParentID *uuid.UUID
}

type Breadcrumb struct {
	NodeID   uuid.UUID
	Filename string
}
type SearchMatch struct {
	FileID     uuid.UUID
	Breadcrumb []Breadcrumb
	Snippet    string
}
type SearchResult struct {
	Node  Node
	Path  string
	Match *SearchMatch
}

type SearchPage struct {
	Items          []SearchResult
	NextCursor     *string
	Degraded       bool
	DegradedReason *string
}
type SearchFilters struct {
	Parent                                                   *Locator
	SemanticType, MediaType                                  *string
	CreatedAfter, CreatedBefore, UpdatedAfter, UpdatedBefore *time.Time
}
type SearchOptions struct {
	Query                   string
	Filters                 SearchFilters
	Limit                   *int32
	Cursor, Sort, Direction *string
}

func parseID(raw string) (uuid.UUID, error) {
	id, err := uuid.Parse(raw)
	if err != nil || id == uuid.Nil {
		return uuid.Nil, scopeError()
	}
	return id, nil
}

func pathContext(value PathContext) (*letfsv1.PathContext, error) {
	if len(value.Mounts) < 1 || len(value.Mounts) > 32 {
		return nil, apperr.New(apperr.Invalid, "VALIDATION", "path context requires 1 to 32 mounts")
	}
	mounts := make([]*letfsv1.Mount, len(value.Mounts))
	for i, mount := range value.Mounts {
		if mount.Path == "" || mount.FilesystemID == uuid.Nil {
			return nil, apperr.New(apperr.Invalid, "VALIDATION", "invalid path mount")
		}
		mounts[i] = &letfsv1.Mount{Path: mount.Path, FilesystemId: mount.FilesystemID.String()}
	}
	return &letfsv1.PathContext{Mounts: mounts}, nil
}

func nativeFilesystem(value *letfsv1.Filesystem) (Filesystem, error) {
	if value == nil {
		return Filesystem{}, scopeError()
	}
	id, err := parseID(value.GetId())
	if err != nil {
		return Filesystem{}, err
	}
	bucket, err := parseID(value.GetBucketId())
	if err != nil {
		return Filesystem{}, err
	}
	root, err := parseID(value.GetRootId())
	if err != nil {
		return Filesystem{}, err
	}
	return Filesystem{ID: id, BucketID: bucket, RootID: root, State: value.GetState()}, nil
}

func nativeNode(value *letfsv1.Node, filesystem uuid.UUID) (Node, error) {
	if value == nil {
		return Node{}, scopeError()
	}
	id, err := parseID(value.GetId())
	if err != nil {
		return Node{}, err
	}
	fs, err := parseID(value.GetFilesystemId())
	if err != nil || fs != filesystem {
		return Node{}, scopeError()
	}
	result := Node{ID: id, FilesystemID: fs, Name: value.GetName(), Kind: value.GetKind(), Revision: value.GetRevision(), SizeBytes: value.GetSizeBytes(), MediaType: value.MediaType, Title: value.Title, Description: value.Description, SemanticType: value.SemanticType, Context: value.Context}
	if value.ParentId != nil {
		parent, err := parseID(value.GetParentId())
		if err != nil {
			return Node{}, err
		}
		result.ParentID = &parent
	}
	if value.GetCreatedAt() != nil {
		result.CreatedAt = value.GetCreatedAt().AsTime()
	}
	if value.GetUpdatedAt() != nil {
		result.UpdatedAt = value.GetUpdatedAt().AsTime()
	}
	return result, nil
}

func (c FilesystemClient) GetFilesystem(ctx context.Context, id uuid.UUID) (Filesystem, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.GetFilesystem(ctx, &letfsv1.GetFilesystemRequest{FilesystemId: id.String()})
	if err != nil {
		return Filesystem{}, rpc.DecodeError(err)
	}
	value, err := nativeFilesystem(response.GetFilesystem())
	if err != nil || value.ID != id {
		return Filesystem{}, scopeError()
	}
	return value, nil
}

func (c FilesystemClient) GetBucketUsage(ctx context.Context, id uuid.UUID) (BucketUsage, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.GetBucketUsage(ctx, &letfsv1.GetBucketUsageRequest{BucketId: id.String()})
	if err != nil {
		return BucketUsage{}, rpc.DecodeError(err)
	}
	bucket, limits := response.GetBucket(), response.GetUploadLimits()
	parsed, err := parseID(bucket.GetId())
	if err != nil || parsed != id || limits == nil {
		return BucketUsage{}, scopeError()
	}
	return BucketUsage{ID: parsed, LimitBytes: bucket.GetLimitBytes(), UsedBytes: bucket.GetUsedBytes(), State: bucket.GetState(), InlineLimitBytes: limits.GetInlineLimitBytes(), MaxFileBytes: limits.GetMaxFileBytes(), MultipartThresholdBytes: limits.GetMultipartThresholdBytes(), MultipartPartBytes: limits.GetMultipartPartBytes()}, nil
}

func (c FilesystemClient) GetNode(ctx context.Context, filesystem, node uuid.UUID, paths PathContext) (Node, error) {
	pathInput, err := pathContext(paths)
	if err != nil {
		return Node{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.GetNode(ctx, &letfsv1.GetNodeRequest{FilesystemId: filesystem.String(), NodeId: node.String(), PathContext: pathInput})
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	value, err := nativeNode(response.GetNode(), filesystem)
	if err != nil || value.ID != node {
		return Node{}, scopeError()
	}
	return value, nil
}

func (c FilesystemClient) ListNodes(ctx context.Context, filesystem, parent uuid.UUID, paths PathContext, limit int32, cursor *string) (NodePage, error) {
	pathInput, err := pathContext(paths)
	if err != nil {
		return NodePage{}, err
	}
	request := &letfsv1.ListNodesRequest{FilesystemId: filesystem.String(), Parent: nodeLocator(parent), PathContext: pathInput, Limit: &limit, Cursor: cursor}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ListNodes(ctx, request)
	if err != nil {
		return NodePage{}, rpc.DecodeError(err)
	}
	items := make([]Node, len(response.GetItems()))
	for i, item := range response.GetItems() {
		items[i], err = nativeNode(item, filesystem)
		if err != nil {
			return NodePage{}, err
		}
	}
	return NodePage{Items: items, NextCursor: response.NextCursor}, nil
}

func nodeLocator(id uuid.UUID) *letfsv1.Locator {
	return &letfsv1.Locator{Target: &letfsv1.Locator_NodeId{NodeId: id.String()}}
}

func nativeLocator(value Locator) (*letfsv1.Locator, error) {
	out := &letfsv1.Locator{}
	switch {
	case value.NodeID != nil && *value.NodeID != uuid.Nil:
		out.Target = &letfsv1.Locator_NodeId{NodeId: value.NodeID.String()}
	case value.Path != nil && *value.Path != "":
		path := &letfsv1.PathLocator{Path: *value.Path}
		if value.CwdID != nil {
			raw := value.CwdID.String()
			path.CwdId = &raw
		}
		out.Target = &letfsv1.Locator_Path{Path: path}
	default:
		return nil, apperr.New(apperr.Invalid, "VALIDATION", "invalid locator")
	}
	if value.ExpectedNodeID != nil {
		raw := value.ExpectedNodeID.String()
		out.ExpectedNodeId = &raw
	}
	if value.ExpectedParentID != nil {
		raw := value.ExpectedParentID.String()
		out.ExpectedParentId = &raw
	}
	return out, nil
}

func (c FilesystemClient) ResolveNode(ctx context.Context, filesystem uuid.UUID, locator Locator, paths PathContext) (Node, error) {
	pathInput, err := pathContext(paths)
	if err != nil {
		return Node{}, err
	}
	locatorInput, err := nativeLocator(locator)
	if err != nil {
		return Node{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ResolveNode(ctx, &letfsv1.ResolveNodeRequest{FilesystemId: filesystem.String(), Locator: locatorInput, PathContext: pathInput})
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	return nativeNode(response.GetNode(), filesystem)
}

func (c FilesystemClient) BatchStat(ctx context.Context, filesystem uuid.UUID, ids []uuid.UUID, paths PathContext) ([]Node, error) {
	pathInput, err := pathContext(paths)
	if err != nil {
		return nil, err
	}
	locators := make([]*letfsv1.Locator, len(ids))
	for i, id := range ids {
		locators[i] = nodeLocator(id)
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.BatchStat(ctx, &letfsv1.BatchStatRequest{FilesystemId: filesystem.String(), Locators: locators, PathContext: pathInput})
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	items := make([]Node, len(response.GetItems()))
	for i, item := range response.GetItems() {
		items[i], err = nativeNode(item, filesystem)
		if err != nil {
			return nil, err
		}
	}
	return items, nil
}

func (c FilesystemClient) CreateDirectory(ctx context.Context, filesystem, key, parent uuid.UUID, paths PathContext, name string) (Node, error) {
	pathInput, err := pathContext(paths)
	if err != nil {
		return Node{}, err
	}
	request := &letfsv1.CreateNodeRequest{FilesystemId: filesystem.String(), IdempotencyKey: key.String(), PathContext: pathInput, Input: &letfsv1.CreateNodeRequest_Directory{Directory: &letfsv1.DirectoryCreation{Parent: nodeLocator(parent), Name: name}}}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CreateNode(ctx, request)
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	return nativeNode(response.GetNode(), filesystem)
}

func (c FilesystemClient) CreateFile(ctx context.Context, filesystem, key, parent uuid.UUID, paths PathContext, name, mediaType string, content []byte) (Node, error) {
	pathInput, err := pathContext(paths)
	if err != nil {
		return Node{}, err
	}
	request := &letfsv1.CreateNodeRequest{FilesystemId: filesystem.String(), IdempotencyKey: key.String(), PathContext: pathInput, Input: &letfsv1.CreateNodeRequest_File{File: &letfsv1.InlineFileCreation{Parent: nodeLocator(parent), Name: name, MediaType: mediaType, Content: content}}}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CreateNode(ctx, request)
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	return nativeNode(response.GetNode(), filesystem)
}

func (c FilesystemClient) UpdateNode(ctx context.Context, filesystem, node uuid.UUID, paths PathContext, revision *int64, name *string, parent *uuid.UUID) (Node, error) {
	pathInput, err := pathContext(paths)
	if err != nil {
		return Node{}, err
	}
	request := &letfsv1.UpdateNodeRequest{FilesystemId: filesystem.String(), Locator: nodeLocator(node), PathContext: pathInput, Revision: revision, Name: name}
	if parent != nil {
		request.Parent = nodeLocator(*parent)
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.UpdateNode(ctx, request)
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	value, err := nativeNode(response.GetNode(), filesystem)
	if err != nil || value.ID != node {
		return Node{}, scopeError()
	}
	return value, nil
}

func nativeSearch(items []*letfsv1.SearchResult, filesystem uuid.UUID) ([]SearchResult, error) {
	result := make([]SearchResult, len(items))
	for i, item := range items {
		node, err := nativeNode(item.GetNode(), filesystem)
		if err != nil {
			return nil, err
		}
		result[i] = SearchResult{Node: node, Path: item.GetPath()}
		if matched := item.GetMatched(); matched != nil {
			fileID, err := parseID(matched.GetFileId())
			if err != nil {
				return nil, err
			}
			breadcrumbs := make([]Breadcrumb, len(matched.GetBreadcrumb()))
			for j, crumb := range matched.GetBreadcrumb() {
				id, err := parseID(crumb.GetNodeId())
				if err != nil {
					return nil, err
				}
				breadcrumbs[j] = Breadcrumb{NodeID: id, Filename: crumb.GetFilename()}
			}
			result[i].Match = &SearchMatch{FileID: fileID, Breadcrumb: breadcrumbs, Snippet: matched.GetSnippet()}
		}
	}
	return result, nil
}
func searchFilters(value SearchFilters) (*letfsv1.SearchFilters, error) {
	out := &letfsv1.SearchFilters{SemanticType: value.SemanticType, MediaType: value.MediaType}
	var err error
	if value.Parent != nil {
		out.Parent, err = nativeLocator(*value.Parent)
		if err != nil {
			return nil, err
		}
	}
	if value.CreatedAfter != nil {
		out.CreatedAfter = timestamppb.New(*value.CreatedAfter)
	}
	if value.CreatedBefore != nil {
		out.CreatedBefore = timestamppb.New(*value.CreatedBefore)
	}
	if value.UpdatedAfter != nil {
		out.UpdatedAfter = timestamppb.New(*value.UpdatedAfter)
	}
	if value.UpdatedBefore != nil {
		out.UpdatedBefore = timestamppb.New(*value.UpdatedBefore)
	}
	return out, nil
}

func (c FilesystemClient) Search(ctx context.Context, filesystem uuid.UUID, paths PathContext, query string, limit int32, cursor *string) (SearchPage, error) {
	pathInput, err := pathContext(paths)
	if err != nil {
		return SearchPage{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.SearchFiles(ctx, &letfsv1.SearchFilesRequest{FilesystemId: filesystem.String(), PathContext: pathInput, Query: query, Limit: &limit, Cursor: cursor})
	if err != nil {
		return SearchPage{}, rpc.DecodeError(err)
	}
	items, err := nativeSearch(response.GetItems(), filesystem)
	if err != nil {
		return SearchPage{}, err
	}
	return SearchPage{Items: items, NextCursor: response.NextCursor, Degraded: response.GetDegraded(), DegradedReason: response.DegradedReason}, nil
}

func (c FilesystemClient) SemanticSearch(ctx context.Context, filesystem uuid.UUID, paths PathContext, query string, limit int32, cursor *string) (SearchPage, error) {
	pathInput, err := pathContext(paths)
	if err != nil {
		return SearchPage{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.SemanticSearch(ctx, &letfsv1.SemanticSearchRequest{FilesystemId: filesystem.String(), PathContext: pathInput, Query: query, Limit: &limit, Cursor: cursor})
	if err != nil {
		return SearchPage{}, rpc.DecodeError(err)
	}
	items, err := nativeSearch(response.GetItems(), filesystem)
	if err != nil {
		return SearchPage{}, err
	}
	return SearchPage{Items: items, NextCursor: response.NextCursor, Degraded: response.GetDegraded(), DegradedReason: response.DegradedReason}, nil
}

func (c FilesystemClient) SearchWithOptions(ctx context.Context, filesystem uuid.UUID, paths PathContext, options SearchOptions) (SearchPage, error) {
	pathInput, err := pathContext(paths)
	if err != nil {
		return SearchPage{}, err
	}
	filters, err := searchFilters(options.Filters)
	if err != nil {
		return SearchPage{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.SearchFiles(ctx, &letfsv1.SearchFilesRequest{FilesystemId: filesystem.String(), Query: options.Query, Filters: filters, Limit: options.Limit, Cursor: options.Cursor, Sort: options.Sort, Direction: options.Direction, PathContext: pathInput})
	if err != nil {
		return SearchPage{}, rpc.DecodeError(err)
	}
	items, err := nativeSearch(response.GetItems(), filesystem)
	if err != nil {
		return SearchPage{}, err
	}
	return SearchPage{Items: items, NextCursor: response.NextCursor, Degraded: response.GetDegraded(), DegradedReason: response.DegradedReason}, nil
}
func (c FilesystemClient) SemanticSearchWithOptions(ctx context.Context, filesystem uuid.UUID, paths PathContext, options SearchOptions) (SearchPage, error) {
	pathInput, err := pathContext(paths)
	if err != nil {
		return SearchPage{}, err
	}
	filters, err := searchFilters(options.Filters)
	if err != nil {
		return SearchPage{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.SemanticSearch(ctx, &letfsv1.SemanticSearchRequest{FilesystemId: filesystem.String(), Query: options.Query, Filters: filters, Limit: options.Limit, Cursor: options.Cursor, PathContext: pathInput})
	if err != nil {
		return SearchPage{}, rpc.DecodeError(err)
	}
	items, err := nativeSearch(response.GetItems(), filesystem)
	if err != nil {
		return SearchPage{}, err
	}
	return SearchPage{Items: items, NextCursor: response.NextCursor, Degraded: response.GetDegraded(), DegradedReason: response.DegradedReason}, nil
}
