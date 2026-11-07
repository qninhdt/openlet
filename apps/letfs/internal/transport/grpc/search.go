package grpc

import (
	"context"
	"time"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func searchFiltersInput(input *letfsv1.SearchFilters) (filesystem.SearchFilters, error) {
	var result filesystem.SearchFilters
	if input == nil {
		return result, nil
	}
	result.SemanticType, result.MediaType = input.SemanticType, input.MediaType
	if input.Parent != nil {
		parent, err := locatorInput(input.Parent)
		if err != nil {
			return result, err
		}
		result.Parent = &parent
	}
	for _, field := range []struct {
		value  *timestamppb.Timestamp
		target **time.Time
	}{{input.CreatedAfter, &result.CreatedAfter}, {input.CreatedBefore, &result.CreatedBefore}, {input.UpdatedAfter, &result.UpdatedAfter}, {input.UpdatedBefore, &result.UpdatedBefore}} {
		if field.value != nil {
			if field.value.CheckValid() != nil {
				return result, rpc.Fault(codes.InvalidArgument, "VALIDATION", "invalid search timestamp")
			}
			value := field.value.AsTime()
			*field.target = &value
		}
	}
	return result, nil
}

func searchResultMessages(items []filesystem.SearchResult) []*letfsv1.SearchResult {
	result := make([]*letfsv1.SearchResult, len(items))
	for i, item := range items {
		result[i] = &letfsv1.SearchResult{Node: nodeMessage(item.Node), Path: item.Path}
		if item.Matched != nil {
			matched := &letfsv1.SearchMatch{FileId: item.Matched.FileID.String(), Snippet: item.Matched.Snippet}
			for _, part := range item.Matched.Breadcrumb {
				matched.Breadcrumb = append(matched.Breadcrumb, &letfsv1.Breadcrumb{NodeId: part.NodeID.String(), Filename: part.Filename})
			}
			result[i].Matched = matched
		}
	}
	return result
}

func (s *Filesystem) SearchFiles(ctx context.Context, input *letfsv1.SearchFilesRequest) (*letfsv1.SearchFilesResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	filters, err := searchFiltersInput(input.GetFilters())
	if err != nil {
		return nil, err
	}
	page, err := s.Store.SearchFiles(ctx, fs, filesystem.SearchInput{Query: input.GetQuery(), Filters: filters, Limit: input.Limit, Cursor: input.Cursor, Sort: input.Sort, Direction: input.Direction})
	if err != nil {
		return nil, err
	}
	return &letfsv1.SearchFilesResponse{Items: searchResultMessages(page.Items), NextCursor: page.NextCursor, Degraded: page.Degraded, DegradedReason: page.DegradedReason}, nil
}

func (s *Filesystem) SemanticSearch(ctx context.Context, input *letfsv1.SemanticSearchRequest) (*letfsv1.SemanticSearchResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	filters, err := searchFiltersInput(input.GetFilters())
	if err != nil {
		return nil, err
	}
	page, err := s.Store.SemanticSearch(ctx, fs, filesystem.SearchInput{Query: input.GetQuery(), Filters: filters, Limit: input.Limit, Cursor: input.Cursor})
	if err != nil {
		return nil, err
	}
	return &letfsv1.SemanticSearchResponse{Items: searchResultMessages(page.Items), NextCursor: page.NextCursor, Degraded: page.Degraded, DegradedReason: page.DegradedReason}, nil
}
