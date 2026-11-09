package grpc

import (
	"context"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
)

func textSearchMessage(value filesystem.TextSearchResult, maxBytes int) *letfsv1.TextSearchResponse {
	result := &letfsv1.TextSearchResponse{Complete: value.Complete, Content: value.Content}
	if value.Stat != nil {
		result.Stat = statMessage(*value.Stat)
	}
	for _, item := range value.Items {
		result.Items = append(result.Items, &letfsv1.TreeEntry{Path: item.Path, Stat: statMessage(item.Stat)})
	}
	if !value.Complete || checkReadSize(result, maxBytes) != nil {
		return &letfsv1.TextSearchResponse{Complete: false}
	}
	return result
}

func (s *Filesystem) TextSearch(ctx context.Context, input *letfsv1.TextSearchRequest) (*letfsv1.TextSearchResponse, error) {
	scope, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	locator, err := locatorInput(input.GetLocator())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.TextSearch(ctx, scope, filesystem.TextSearchInput{Locator: locator, Mode: input.Mode, Text: input.Text, IgnoreCase: input.IgnoreCase, MaxFiles: input.MaxFiles, MaxLines: input.MaxLines, MaxBytes: input.MaxBytes})
	if err != nil {
		return nil, err
	}
	maxBytes := filesystem.MaxReadBytes
	if input.MaxBytes != nil {
		maxBytes = int(*input.MaxBytes)
	}
	return textSearchMessage(value, maxBytes), nil
}
