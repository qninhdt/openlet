package grpc

import (
	"context"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/qninhdt/openlet/packages/go/apperr"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	"google.golang.org/protobuf/proto"
)

func statMessage(value filesystem.FileStat) *letfsv1.FileStat {
	return &letfsv1.FileStat{Node: nodeMessage(value.Node), StorageKind: value.StorageKind, RepresentationKind: value.RepresentationKind, ReadableSize: value.ReadableSize, Fingerprint: value.Fingerprint, NewlineCount: value.NewlineCount, Sha256: value.SHA256}
}

func checkReadSize(value proto.Message, maxBytes int) error {
	if proto.Size(value) > maxBytes || proto.Size(value) > rpc.MaxMessageBytes-1024 {
		return apperr.New(apperr.Limit, "RESOURCE_LIMIT", "read response exceeds limit")
	}
	return nil
}

func (s *Filesystem) ReadImage(ctx context.Context, input *letfsv1.ReadImageRequest) (*letfsv1.ReadImageResponse, error) {
	scope, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	locator, err := locatorInput(input.GetLocator())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.ReadImage(ctx, scope, locator, input.ExpectedFingerprint)
	if err != nil {
		return nil, err
	}
	result := &letfsv1.ReadImageResponse{Stat: statMessage(value.Stat), Content: value.Content, Mime: "image/png", Width: int32(value.Width), Height: int32(value.Height), Sha256: value.SHA256}
	return result, checkReadSize(result, rpc.MaxMessageBytes-1024)
}

func (s *Filesystem) Stat(ctx context.Context, input *letfsv1.StatRequest) (*letfsv1.StatResponse, error) {
	scope, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	locator, err := locatorInput(input.GetLocator())
	if err != nil {
		return nil, err
	}
	stat, err := s.Store.Stat(ctx, scope, locator, input.GetContentCheck())
	if err != nil {
		return nil, err
	}
	result := &letfsv1.StatResponse{Stat: statMessage(stat)}
	return result, checkReadSize(result, filesystem.MaxReadBytes)
}

func (s *Filesystem) ReadText(ctx context.Context, input *letfsv1.ReadTextRequest) (*letfsv1.ReadTextResponse, error) {
	scope, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	locator, err := locatorInput(input.GetLocator())
	if err != nil {
		return nil, err
	}
	selection := filesystem.TextSelection{}
	switch value := input.Selection.(type) {
	case *letfsv1.ReadTextRequest_Whole:
		if value.Whole != nil {
			selection.Kind = "whole"
		}
	case *letfsv1.ReadTextRequest_Bytes:
		if value.Bytes != nil {
			selection = filesystem.TextSelection{Kind: "bytes", Offset: value.Bytes.Offset, Length: value.Bytes.Length}
		}
	case *letfsv1.ReadTextRequest_Lines:
		if value.Lines != nil {
			selection = filesystem.TextSelection{Kind: "lines", StartLine: value.Lines.StartLine, LineCount: value.Lines.LineCount}
		}
	case *letfsv1.ReadTextRequest_Head:
		if value.Head != nil {
			selection = filesystem.TextSelection{Kind: "head", LineCount: value.Head.LineCount}
		}
	case *letfsv1.ReadTextRequest_Tail:
		if value.Tail != nil {
			selection = filesystem.TextSelection{Kind: "tail", LineCount: value.Tail.LineCount}
		}
	}
	read, err := s.Store.ReadText(ctx, scope, locator, selection, input.ExpectedFingerprint)
	if err != nil {
		return nil, err
	}
	result := &letfsv1.ReadTextResponse{Stat: statMessage(read.Stat), Content: read.Content, Offset: read.Offset, Length: read.Length}
	return result, checkReadSize(result, rpc.MaxMessageBytes-1024)
}

func (s *Filesystem) TextMetrics(ctx context.Context, input *letfsv1.TextMetricsRequest) (*letfsv1.TextMetricsResponse, error) {
	scope, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	locator, err := locatorInput(input.GetLocator())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.TextMetrics(ctx, scope, locator, input.GetAlgorithm())
	if err != nil {
		return nil, err
	}
	result := &letfsv1.TextMetricsResponse{Stat: statMessage(value.Stat), Algorithm: value.Algorithm, Digest: value.Digest, Supported: value.Supported}
	return result, checkReadSize(result, filesystem.MaxReadBytes)
}

func (s *Filesystem) ReadTree(ctx context.Context, input *letfsv1.ReadTreeRequest) (*letfsv1.ReadTreeResponse, error) {
	scope, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	root, err := locatorInput(input.GetRoot())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.ReadTree(ctx, scope, root, filesystem.TreeOptions{Depth: input.Depth, Cursor: input.Cursor, Limit: input.Limit, MaxBytes: input.MaxBytes})
	if err != nil {
		return nil, err
	}
	result := &letfsv1.ReadTreeResponse{Items: make([]*letfsv1.TreeEntry, 0, len(value.Items)), NextCursor: value.NextCursor, Complete: value.Complete}
	for _, item := range value.Items {
		result.Items = append(result.Items, &letfsv1.TreeEntry{Path: item.Path, Stat: statMessage(item.Stat)})
	}
	maxBytes := filesystem.MaxReadBytes
	if input.MaxBytes != nil {
		maxBytes = int(*input.MaxBytes)
	}
	return result, checkReadSize(result, maxBytes)
}
