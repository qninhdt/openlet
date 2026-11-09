package letfs

import (
	"context"

	"github.com/google/uuid"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
)

type FileStat struct {
	Node                                         Node
	StorageKind, RepresentationKind, Fingerprint string
	ReadableSize                                 int64
	NewlineCount                                 *int64
	SHA256                                       *string
}

type TextSelection struct {
	Kind                 string
	Offset               int64
	Length               *int64
	StartLine, LineCount int64
}

type TextRead struct {
	Stat           FileStat
	Content        []byte
	Offset, Length int64
}

type TextMetric struct {
	Stat              FileStat
	Algorithm, Digest string
	Supported         bool
}

type TreeOptions struct {
	Depth, Limit, MaxBytes *int32
	Cursor                 *string
}

type TreeEntry struct {
	Path string
	Stat FileStat
}

type TreePage struct {
	Items      []TreeEntry
	NextCursor *string
	Complete   bool
}

type ImageRead struct {
	Stat          FileStat
	Content       []byte
	Mime, SHA256  string
	Width, Height int32
}

func nativeStat(value *letfsv1.FileStat, scope uuid.UUID, locator *Locator) (FileStat, error) {
	if value == nil || value.GetReadableSize() < 0 || value.GetFingerprint() == "" {
		return FileStat{}, scopeError()
	}
	node, err := nativeNode(value.GetNode(), scope)
	if err != nil {
		return FileStat{}, err
	}
	if locator != nil && (locator.NodeID != nil && node.ID != *locator.NodeID || locator.ExpectedNodeID != nil && node.ID != *locator.ExpectedNodeID) {
		return FileStat{}, scopeError()
	}
	switch value.GetRepresentationKind() {
	case "directory":
		if node.Kind != "directory" {
			return FileStat{}, scopeError()
		}
	case "text", "blob_metadata":
		if node.Kind != "file" {
			return FileStat{}, scopeError()
		}
	default:
		return FileStat{}, scopeError()
	}
	return FileStat{Node: node, StorageKind: value.StorageKind, RepresentationKind: value.RepresentationKind, Fingerprint: value.Fingerprint, ReadableSize: value.ReadableSize, NewlineCount: value.NewlineCount, SHA256: value.Sha256}, nil
}

func (c FilesystemClient) Stat(ctx context.Context, fs, scope uuid.UUID, locator Locator, contentCheck bool) (FileStat, error) {
	loc, err := nativeLocator(locator)
	if err != nil {
		return FileStat{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.Stat(ctx, &letfsv1.StatRequest{FilesystemId: fs.String(), ScopeId: scope.String(), Locator: loc, ContentCheck: contentCheck})
	if err != nil {
		return FileStat{}, rpc.DecodeError(err)
	}
	return nativeStat(response.GetStat(), scope, &locator)
}

func (c FilesystemClient) ReadText(ctx context.Context, fs, scope uuid.UUID, locator Locator, selection TextSelection, expected *string) (TextRead, error) {
	loc, err := nativeLocator(locator)
	if err != nil {
		return TextRead{}, err
	}
	request := &letfsv1.ReadTextRequest{FilesystemId: fs.String(), ScopeId: scope.String(), Locator: loc, ExpectedFingerprint: expected}
	switch selection.Kind {
	case "whole":
		request.Selection = &letfsv1.ReadTextRequest_Whole{Whole: &letfsv1.WholeText{}}
	case "bytes":
		request.Selection = &letfsv1.ReadTextRequest_Bytes{Bytes: &letfsv1.ByteRange{Offset: selection.Offset, Length: selection.Length}}
	case "lines":
		request.Selection = &letfsv1.ReadTextRequest_Lines{Lines: &letfsv1.LineRange{StartLine: selection.StartLine, LineCount: selection.LineCount}}
	case "head":
		request.Selection = &letfsv1.ReadTextRequest_Head{Head: &letfsv1.LineCount{LineCount: selection.LineCount}}
	case "tail":
		request.Selection = &letfsv1.ReadTextRequest_Tail{Tail: &letfsv1.LineCount{LineCount: selection.LineCount}}
	default:
		return TextRead{}, scopeError()
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ReadText(ctx, request)
	if err != nil {
		return TextRead{}, rpc.DecodeError(err)
	}
	stat, err := nativeStat(response.GetStat(), scope, &locator)
	if err != nil {
		return TextRead{}, err
	}
	if response.Offset < 0 || response.Offset > stat.ReadableSize || response.Length != int64(len(response.Content)) || response.Length > stat.ReadableSize-response.Offset || expected != nil && stat.Fingerprint != *expected {
		return TextRead{}, scopeError()
	}
	return TextRead{Stat: stat, Content: response.Content, Offset: response.Offset, Length: response.Length}, nil
}

func (c FilesystemClient) TextMetrics(ctx context.Context, fs, scope uuid.UUID, locator Locator, algorithm string) (TextMetric, error) {
	loc, err := nativeLocator(locator)
	if err != nil {
		return TextMetric{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.TextMetrics(ctx, &letfsv1.TextMetricsRequest{FilesystemId: fs.String(), ScopeId: scope.String(), Locator: loc, Algorithm: algorithm})
	if err != nil {
		return TextMetric{}, rpc.DecodeError(err)
	}
	stat, err := nativeStat(response.GetStat(), scope, &locator)
	if err != nil {
		return TextMetric{}, err
	}
	return TextMetric{Stat: stat, Algorithm: response.Algorithm, Digest: response.Digest, Supported: response.Supported}, nil
}

func (c FilesystemClient) ReadTree(ctx context.Context, fs, scope uuid.UUID, root Locator, options TreeOptions) (TreePage, error) {
	loc, err := nativeLocator(root)
	if err != nil {
		return TreePage{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ReadTree(ctx, &letfsv1.ReadTreeRequest{FilesystemId: fs.String(), ScopeId: scope.String(), Root: loc, Depth: options.Depth, Limit: options.Limit, MaxBytes: options.MaxBytes, Cursor: options.Cursor})
	if err != nil {
		return TreePage{}, rpc.DecodeError(err)
	}
	if response == nil || response.Complete != (response.NextCursor == nil) {
		return TreePage{}, scopeError()
	}
	page := TreePage{Items: make([]TreeEntry, 0, len(response.Items)), NextCursor: response.NextCursor, Complete: response.Complete}
	for _, item := range response.Items {
		stat, err := nativeStat(item.GetStat(), scope, nil)
		if err != nil {
			return TreePage{}, err
		}
		page.Items = append(page.Items, TreeEntry{Path: item.GetPath(), Stat: stat})
	}
	return page, nil
}

func (c FilesystemClient) ReadImage(ctx context.Context, fs, scope uuid.UUID, locator Locator, expected *string) (ImageRead, error) {
	loc, err := nativeLocator(locator)
	if err != nil {
		return ImageRead{}, err
	}
	ctx, cancel := bounded(ctx)
	defer cancel()
	response, err := c.API.ReadImage(ctx, &letfsv1.ReadImageRequest{FilesystemId: fs.String(), ScopeId: scope.String(), Locator: loc, ExpectedFingerprint: expected})
	if err != nil {
		return ImageRead{}, rpc.DecodeError(err)
	}
	stat, err := nativeStat(response.GetStat(), scope, &locator)
	if err != nil {
		return ImageRead{}, err
	}
	if response.Mime != "image/png" || response.Width < 1 || response.Width > 2048 || response.Height < 1 || response.Height > 2048 || len(response.Content) == 0 || response.Sha256 == "" || expected != nil && stat.Fingerprint != *expected {
		return ImageRead{}, scopeError()
	}
	return ImageRead{Stat: stat, Content: response.Content, Mime: response.Mime, Width: response.Width, Height: response.Height, SHA256: response.Sha256}, nil
}
