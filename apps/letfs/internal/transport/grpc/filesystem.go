package grpc

import (
	"context"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type Filesystem struct {
	letfsv1.UnimplementedFilesystemServiceServer
	Store   *filesystem.Store
	Service *filesystem.Service
}

func nodeMessage(node filesystem.Node) *letfsv1.Node {
	var parent *string
	if node.ParentID != nil {
		value := node.ParentID.String()
		parent = &value
	}
	return &letfsv1.Node{Id: node.ID.String(), ScopeId: node.ScopeID.String(), ParentId: parent,
		Name: node.Name, Kind: node.Kind, Revision: node.Revision, SizeBytes: node.SizeBytes,
		CreatedAt: timestamppb.New(node.CreatedAt), UpdatedAt: timestamppb.New(node.UpdatedAt), MediaType: node.MediaType,
		Title: node.Title, Description: node.Description, SemanticType: node.SemanticType, Context: node.Context}
}

func (s *Filesystem) scopeInput(ctx context.Context, fs, scope string) (uuid.UUID, error) {
	filesystemID, err := parseID(fs)
	if err != nil {
		return uuid.Nil, err
	}
	scopeID, err := parseID(scope)
	if err != nil {
		return uuid.Nil, err
	}
	return scopeID, s.Store.ValidateScope(ctx, filesystemID, scopeID)
}

func optionalID(value *string) (*uuid.UUID, error) {
	if value == nil {
		return nil, nil
	}
	id, err := parseID(*value)
	return &id, err
}

func locatorInput(value *letfsv1.Locator) (filesystem.Locator, error) {
	var result filesystem.Locator
	if value == nil {
		return result, rpc.Fault(codes.InvalidArgument, "VALIDATION", "locator required")
	}
	var err error
	switch target := value.Target.(type) {
	case *letfsv1.Locator_NodeId:
		result.NodeID, err = optionalID(&target.NodeId)
	case *letfsv1.Locator_Path:
		if target.Path == nil {
			return result, rpc.Fault(codes.InvalidArgument, "VALIDATION", "path required")
		}
		result.Path = &target.Path.Path
		result.CwdID, err = optionalID(target.Path.CwdId)
	default:
		return result, rpc.Fault(codes.InvalidArgument, "VALIDATION", "locator target required")
	}
	if err != nil {
		return result, err
	}
	result.ExpectedNodeID, err = optionalID(value.ExpectedNodeId)
	if err != nil {
		return result, err
	}
	result.ExpectedParentID, err = optionalID(value.ExpectedParentId)
	return result, err
}

func (s *Filesystem) GetFilesystem(ctx context.Context, input *letfsv1.GetFilesystemRequest) (*letfsv1.GetFilesystemResponse, error) {
	id, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.GetFilesystem(ctx, id)
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetFilesystemResponse{Filesystem: filesystemMessage(value)}, nil
}

func (s *Filesystem) GetNode(ctx context.Context, input *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetNodeId())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.GetNode(ctx, fs, filesystem.Locator{NodeID: &id})
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetNodeResponse{Node: nodeMessage(value)}, nil
}

func (s *Filesystem) ResolveNode(ctx context.Context, input *letfsv1.ResolveNodeRequest) (*letfsv1.ResolveNodeResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	locator, err := locatorInput(input.GetLocator())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.ResolveNode(ctx, fs, locator)
	if err != nil {
		return nil, err
	}
	return &letfsv1.ResolveNodeResponse{Node: nodeMessage(value)}, nil
}

func (s *Filesystem) BatchStat(ctx context.Context, input *letfsv1.BatchStatRequest) (*letfsv1.BatchStatResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	if len(input.GetLocators()) < 1 || len(input.GetLocators()) > 100 {
		return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "locator batch must contain 1..100 items")
	}
	locators := make([]filesystem.Locator, len(input.Locators))
	for i, value := range input.Locators {
		locators[i], err = locatorInput(value)
		if err != nil {
			return nil, err
		}
	}
	values, err := s.Store.BatchStat(ctx, fs, locators)
	if err != nil {
		return nil, err
	}
	result := &letfsv1.BatchStatResponse{Items: make([]*letfsv1.Node, len(values))}
	for i, value := range values {
		result.Items[i] = nodeMessage(value)
	}
	return result, nil
}

func (s *Filesystem) ListNodes(ctx context.Context, input *letfsv1.ListNodesRequest) (*letfsv1.ListNodesResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	parent, err := locatorInput(input.GetParent())
	if err != nil {
		return nil, err
	}
	page, err := s.Store.ListNodes(ctx, fs, parent, input.Cursor, input.Limit)
	if err != nil {
		return nil, err
	}
	result := &letfsv1.ListNodesResponse{Items: make([]*letfsv1.Node, len(page.Items)), NextCursor: page.NextCursor}
	for i, value := range page.Items {
		result.Items[i] = nodeMessage(value)
	}
	return result, nil
}

func (s *Filesystem) CreateNode(ctx context.Context, input *letfsv1.CreateNodeRequest) (*letfsv1.CreateNodeResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	key, err := parseID(input.GetIdempotencyKey())
	if err != nil {
		return nil, err
	}
	var creation filesystem.CreateNode
	var parent *letfsv1.Locator
	switch value := input.Input.(type) {
	case *letfsv1.CreateNodeRequest_Directory:
		if value.Directory != nil {
			parent, creation.Name = value.Directory.Parent, value.Directory.Name
		}
	case *letfsv1.CreateNodeRequest_File:
		if value.File != nil {
			parent, creation.Name = value.File.Parent, value.File.Name
			creation.File = &filesystem.InlineFile{Content: value.File.Content, MediaType: value.File.MediaType}
		}
	}
	creation.Parent, err = locatorInput(parent)
	if err != nil {
		return nil, err
	}
	node, err := s.Service.CreateNode(ctx, fs, key, creation)
	if err != nil {
		return nil, err
	}
	return &letfsv1.CreateNodeResponse{Node: nodeMessage(node)}, nil
}

func (s *Filesystem) UpdateNode(ctx context.Context, input *letfsv1.UpdateNodeRequest) (*letfsv1.UpdateNodeResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	locator, err := locatorInput(input.GetLocator())
	if err != nil {
		return nil, err
	}
	patch := filesystem.UpdateNode{Locator: locator, Revision: input.Revision, Name: input.Name}
	if input.Parent != nil {
		parent, err := locatorInput(input.Parent)
		if err != nil {
			return nil, err
		}
		patch.Parent = &parent
	}
	node, err := s.Service.UpdateNode(ctx, fs, patch)
	if err != nil {
		return nil, err
	}
	return &letfsv1.UpdateNodeResponse{Node: nodeMessage(node)}, nil
}

func (s *Filesystem) ReplaceContent(ctx context.Context, input *letfsv1.ReplaceContentRequest) (*letfsv1.ReplaceContentResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	locator, err := locatorInput(input.GetLocator())
	if err != nil {
		return nil, err
	}
	node, err := s.Service.ReplaceContent(ctx, fs, locator, input.Revision, input.Content, input.MediaType)
	if err != nil {
		return nil, err
	}
	return &letfsv1.ReplaceContentResponse{Node: nodeMessage(node)}, nil
}
