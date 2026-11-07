package grpc

import (
	"context"

	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
)

func (s *Filesystem) GetDownload(ctx context.Context, input *letfsv1.GetDownloadRequest) (*letfsv1.GetDownloadResponse, error) {
	fs, err := s.scopeInput(ctx, input.GetFilesystemId(), input.GetScopeId())
	if err != nil {
		return nil, err
	}
	id, err := parseID(input.GetNodeId())
	if err != nil {
		return nil, err
	}
	value, err := s.Store.GetDownload(ctx, fs, id, input.Revision)
	if err != nil {
		return nil, err
	}
	result := &letfsv1.Download{Mime: value.MIME, Filename: value.Filename, Etag: value.ETag, SizeBytes: value.SizeBytes}
	if value.SignedURL != "" {
		result.Source = &letfsv1.Download_SignedUrl{SignedUrl: value.SignedURL}
	} else {
		result.Source = &letfsv1.Download_InlineContent{InlineContent: value.InlineContent}
	}
	return &letfsv1.GetDownloadResponse{Download: result}, nil
}
