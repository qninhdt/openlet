package grpc

import (
	"context"

	"github.com/google/uuid"
	"google.golang.org/grpc/codes"
	"google.golang.org/protobuf/types/known/timestamppb"
	"openlet/apps/letfs/internal/filesystem"
	"openlet/apps/letfs/internal/temporal"
	letfsv1 "openlet/packages/go/gen/openlet_api/letfs/v1"
	"openlet/packages/go/rpc"
)

type Filesystem struct {
	letfsv1.UnimplementedFilesystemServiceServer
	Store *filesystem.Store
	Jobs  *temporal.Jobs
}

func nodeMessage(node filesystem.Node) *letfsv1.Node {
	var parent *string
	if node.ParentID != nil {
		value := node.ParentID.String()
		parent = &value
	}
	return &letfsv1.Node{Id: node.ID.String(), FilesystemId: node.FilesystemID.String(), ParentId: parent,
		Name: node.Name, Kind: node.Kind, Revision: node.Revision, SizeBytes: node.SizeBytes,
		CreatedAt: timestamppb.New(node.CreatedAt), UpdatedAt: timestamppb.New(node.UpdatedAt), MediaType: node.MediaType,
		Title: node.Title, Description: node.Description, SemanticType: node.SemanticType, Context: node.Context}
}

func pathInput(value *letfsv1.PathContext) ([]filesystem.Mount, error) {
	if len(value.GetMounts()) < 1 || len(value.GetMounts()) > 32 {
		return nil, rpc.Fault(codes.InvalidArgument, "VALIDATION", "1..32 mounts required")
	}
	mounts := make([]filesystem.Mount, len(value.Mounts))
	for i, mount := range value.Mounts {
		id, err := parseID(mount.GetFilesystemId())
		if err != nil {
			return nil, err
		}
		mounts[i] = filesystem.Mount{Path: mount.GetPath(), FilesystemID: id}
	}
	return mounts, nil
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
	return &letfsv1.GetFilesystemResponse{Filesystem: &letfsv1.Filesystem{Id: value.ID.String(), BucketId: value.BucketID.String(), RootId: value.RootID.String(), State: value.State}}, nil
}

func (s *Filesystem) GetBucketUsage(ctx context.Context, input *letfsv1.GetBucketUsageRequest) (*letfsv1.GetBucketUsageResponse, error) {
	id, err := parseID(input.GetBucketId())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.GetBucketUsage(ctx, id)
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetBucketUsageResponse{Bucket: bucketMessage(value), UploadLimits: &letfsv1.UploadLimits{
		InlineLimitBytes: s.Store.InlineLimit, MaxFileBytes: s.Store.MaxFileBytes,
		MultipartThresholdBytes: s.Store.MultipartThreshold, MultipartPartBytes: s.Store.MultipartPartBytes,
	}}, nil
}

func (s *Filesystem) GetNode(ctx context.Context, input *letfsv1.GetNodeRequest) (*letfsv1.GetNodeResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetNodeId())
	if err != nil {
		return nil, err
	}
	mounts, err := pathInput(input.GetPathContext())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.GetNode(ctx, fs, mounts, filesystem.Locator{NodeID: &id})
	if err != nil {
		return nil, err
	}
	return &letfsv1.GetNodeResponse{Node: nodeMessage(value)}, nil
}

func (s *Filesystem) ResolveNode(ctx context.Context, input *letfsv1.ResolveNodeRequest) (*letfsv1.ResolveNodeResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	mounts, err := pathInput(input.GetPathContext())
	if err != nil {
		return nil, err
	}
	locator, err := locatorInput(input.GetLocator())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.ResolveNode(ctx, fs, mounts, locator)
	if err != nil {
		return nil, err
	}
	return &letfsv1.ResolveNodeResponse{Node: nodeMessage(value)}, nil
}

func (s *Filesystem) BatchStat(ctx context.Context, input *letfsv1.BatchStatRequest) (*letfsv1.BatchStatResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	mounts, err := pathInput(input.GetPathContext())
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
	values, err := s.Store.BatchStat(ctx, fs, mounts, locators)
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
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	mounts, err := pathInput(input.GetPathContext())
	if err != nil {
		return nil, err
	}
	parent, err := locatorInput(input.GetParent())
	if err != nil {
		return nil, err
	}
	page, err := s.Store.ListNodes(ctx, fs, mounts, parent, input.Cursor, input.Limit)
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
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	key, err := parseID(input.GetIdempotencyKey())
	if err != nil {
		return nil, err
	}
	mounts, err := pathInput(input.GetPathContext())
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
	node, err := s.Store.CreateNode(ctx, fs, mounts, key, creation)
	if err != nil {
		return nil, err
	}
	if node.Kind == "file" {
		s.dispatchPending(ctx, node.ID)
	}
	return &letfsv1.CreateNodeResponse{Node: nodeMessage(node)}, nil
}

func (s *Filesystem) UpdateNode(ctx context.Context, input *letfsv1.UpdateNodeRequest) (*letfsv1.UpdateNodeResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	mounts, err := pathInput(input.GetPathContext())
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
	node, err := s.Store.UpdateNode(ctx, fs, mounts, patch)
	if err != nil {
		return nil, err
	}
	return &letfsv1.UpdateNodeResponse{Node: nodeMessage(node)}, nil
}

func (s *Filesystem) ReplaceContent(ctx context.Context, input *letfsv1.ReplaceContentRequest) (*letfsv1.ReplaceContentResponse, error) {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return nil, err
	}
	mounts, err := pathInput(input.GetPathContext())
	if err != nil {
		return nil, err
	}
	locator, err := locatorInput(input.GetLocator())
	if err != nil {
		return nil, err
	}
	node, err := s.Store.ReplaceContent(ctx, fs, mounts, locator, input.Revision, input.Content, input.MediaType)
	if err != nil {
		return nil, err
	}
	s.dispatchPending(ctx, node.ID)
	return &letfsv1.ReplaceContentResponse{Node: nodeMessage(node)}, nil
}
