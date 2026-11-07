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
	ID                               uuid.UUID
	LimitBytes, UsedBytes, NodeCount int64
	State                            string
}

type Node struct {
	ID, ScopeID  uuid.UUID
	ParentID     *uuid.UUID
	Name, Kind   string
	Revision     int64
	SizeBytes    int64
	MediaType    *string
	CreatedAt    time.Time
	UpdatedAt    time.Time
	Title        *string
	Description  *string
	SemanticType *string
	Context      *string
}

type NodePage struct {
	Items      []Node
	NextCursor *string
}

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
type SemanticSearchResults struct {
	Items          []SearchResult
	Degraded       bool
	DegradedReason *string
}
type SemanticSearchOptions struct {
	Query   string
	Filters SearchFilters
	Limit   *int32
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

func nativeFilesystem(value *letfsv1.Filesystem) (Filesystem, error) {
	if value == nil {
		return Filesystem{}, scopeError()
	}
	id, err := parseID(value.GetId())
	if err != nil {
		return Filesystem{}, err
	}
	if value.GetLimitBytes() < 0 || value.GetUsedBytes() < 0 || value.GetNodeCount() < 0 {
		return Filesystem{}, scopeError()
	}
	return Filesystem{ID: id, LimitBytes: value.LimitBytes, UsedBytes: value.UsedBytes, NodeCount: value.NodeCount, State: value.State}, nil
}

func nativeNode(value *letfsv1.Node, filesystem uuid.UUID) (Node, error) {
	if value == nil {
		return Node{}, scopeError()
	}
	id, err := parseID(value.GetId())
	if err != nil {
		return Node{}, err
	}
	fs, err := parseID(value.GetScopeId())
	if err != nil || fs != filesystem {
		return Node{}, scopeError()
	}
	result := Node{ID: id, ScopeID: fs, Name: value.GetName(), Kind: value.GetKind(), Revision: value.GetRevision(), SizeBytes: value.GetSizeBytes(), MediaType: value.MediaType, Title: value.Title, Description: value.Description, SemanticType: value.SemanticType, Context: value.Context}
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

func (c FilesystemClient) GetNode(ctx context.Context, filesystem, scope, node uuid.UUID) (Node, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.GetNode(ctx, &letfsv1.GetNodeRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), NodeId: node.String()})
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	value, err := nativeNode(response.GetNode(), scope)
	if err != nil || value.ID != node {
		return Node{}, scopeError()
	}
	return value, nil
}

func (c FilesystemClient) ListNodes(ctx context.Context, filesystem, scope, parent uuid.UUID, limit int32, cursor *string) (NodePage, error) {
	request := &letfsv1.ListNodesRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), Parent: nodeLocator(parent), Limit: &limit, Cursor: cursor}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ListNodes(ctx, request)
	if err != nil {
		return NodePage{}, rpc.DecodeError(err)
	}
	items := make([]Node, len(response.GetItems()))
	for i, item := range response.GetItems() {
		items[i], err = nativeNode(item, scope)
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

func (c FilesystemClient) ResolveNode(ctx context.Context, filesystem, scope uuid.UUID, locator Locator) (Node, error) {
	locatorInput, err := nativeLocator(locator)
	if err != nil {
		return Node{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ResolveNode(ctx, &letfsv1.ResolveNodeRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), Locator: locatorInput})
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	return nativeNode(response.GetNode(), scope)
}

type ScopedLocator struct {
	ScopeID uuid.UUID
	Locator Locator
}

func (c FilesystemClient) BatchStat(ctx context.Context, filesystem uuid.UUID, locators []ScopedLocator) ([]Node, error) {
	request := &letfsv1.BatchStatRequest{FilesystemId: filesystem.String()}
	for _, item := range locators {
		locator, err := nativeLocator(item.Locator)
		if err != nil {
			return nil, err
		}
		request.Locators = append(request.Locators, &letfsv1.ScopedLocator{ScopeId: item.ScopeID.String(), Locator: locator})
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.BatchStat(ctx, request)
	if err != nil {
		return nil, rpc.DecodeError(err)
	}
	if len(response.Items) != len(locators) {
		return nil, scopeError()
	}
	nodes := make([]Node, len(locators))
	for i, item := range response.Items {
		nodes[i], err = nativeNode(item, locators[i].ScopeID)
		if err != nil {
			return nil, err
		}
	}
	return nodes, nil
}

func (c FilesystemClient) CreateDirectory(ctx context.Context, filesystem, scope, key, parent uuid.UUID, name string) (Node, error) {
	request := &letfsv1.CreateNodeRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), IdempotencyKey: key.String(), Input: &letfsv1.CreateNodeRequest_Directory{Directory: &letfsv1.DirectoryCreation{Parent: nodeLocator(parent), Name: name}}}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CreateNode(ctx, request)
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	return nativeNode(response.GetNode(), scope)
}

func (c FilesystemClient) CreateFile(ctx context.Context, filesystem, scope, key, parent uuid.UUID, name, mediaType string, content []byte) (Node, error) {
	request := &letfsv1.CreateNodeRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), IdempotencyKey: key.String(), Input: &letfsv1.CreateNodeRequest_File{File: &letfsv1.InlineFileCreation{Parent: nodeLocator(parent), Name: name, MediaType: mediaType, Content: content}}}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.CreateNode(ctx, request)
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	return nativeNode(response.GetNode(), scope)
}

func (c FilesystemClient) UpdateNode(ctx context.Context, filesystem, scope, node uuid.UUID, revision *int64, name *string, parent *uuid.UUID, destinationScope *uuid.UUID) (Node, error) {
	request := &letfsv1.UpdateNodeRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), Locator: nodeLocator(node), Revision: revision, Name: name, DestinationScopeId: uuidString(destinationScope)}
	if parent != nil {
		request.Parent = nodeLocator(*parent)
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.UpdateNode(ctx, request)
	if err != nil {
		return Node{}, rpc.DecodeError(err)
	}
	expected := scope
	if destinationScope != nil {
		expected = *destinationScope
	}
	value, err := nativeNode(response.GetNode(), expected)
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

func (c FilesystemClient) Search(ctx context.Context, filesystem, scope uuid.UUID, query string, limit int32, cursor *string) (SearchPage, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.SearchFiles(ctx, &letfsv1.SearchFilesRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), Query: query, Limit: &limit, Cursor: cursor})
	if err != nil {
		return SearchPage{}, rpc.DecodeError(err)
	}
	items, err := nativeSearch(response.GetItems(), scope)
	if err != nil {
		return SearchPage{}, err
	}
	return SearchPage{Items: items, NextCursor: response.NextCursor, Degraded: response.GetDegraded(), DegradedReason: response.DegradedReason}, nil
}

func (c FilesystemClient) SemanticSearch(ctx context.Context, filesystem, scope uuid.UUID, query string, limit int32) (SemanticSearchResults, error) {
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.SemanticSearch(ctx, &letfsv1.SemanticSearchRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), Query: query, Limit: &limit})
	if err != nil {
		return SemanticSearchResults{}, rpc.DecodeError(err)
	}
	items, err := nativeSearch(response.GetItems(), scope)
	if err != nil {
		return SemanticSearchResults{}, err
	}
	return SemanticSearchResults{Items: items, Degraded: response.GetDegraded(), DegradedReason: response.DegradedReason}, nil
}

func (c FilesystemClient) SearchWithOptions(ctx context.Context, filesystem, scope uuid.UUID, options SearchOptions) (SearchPage, error) {
	filters, err := searchFilters(options.Filters)
	if err != nil {
		return SearchPage{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.SearchFiles(ctx, &letfsv1.SearchFilesRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), Query: options.Query, Filters: filters, Limit: options.Limit, Cursor: options.Cursor, Sort: options.Sort, Direction: options.Direction})
	if err != nil {
		return SearchPage{}, rpc.DecodeError(err)
	}
	items, err := nativeSearch(response.GetItems(), scope)
	if err != nil {
		return SearchPage{}, err
	}
	return SearchPage{Items: items, NextCursor: response.NextCursor, Degraded: response.GetDegraded(), DegradedReason: response.DegradedReason}, nil
}
func (c FilesystemClient) SemanticSearchWithOptions(ctx context.Context, filesystem, scope uuid.UUID, options SemanticSearchOptions) (SemanticSearchResults, error) {
	filters, err := searchFilters(options.Filters)
	if err != nil {
		return SemanticSearchResults{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.SemanticSearch(ctx, &letfsv1.SemanticSearchRequest{FilesystemId: filesystem.String(), ScopeId: scope.String(), Query: options.Query, Filters: filters, Limit: options.Limit})
	if err != nil {
		return SemanticSearchResults{}, rpc.DecodeError(err)
	}
	items, err := nativeSearch(response.GetItems(), scope)
	if err != nil {
		return SemanticSearchResults{}, err
	}
	return SemanticSearchResults{Items: items, Degraded: response.GetDegraded(), DegradedReason: response.DegradedReason}, nil
}
