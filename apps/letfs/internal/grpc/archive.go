package grpc

import (
	"errors"
	"io"

	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/qninhdt/openlet/packages/go/rpc"
	grpcgo "google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func (s *Filesystem) StreamArchive(input *letfsv1.StreamArchiveRequest, stream grpcgo.ServerStreamingServer[letfsv1.StreamArchiveResponse]) error {
	fs, err := parseID(input.GetFilesystemId())
	if err != nil {
		return err
	}
	id, err := parseID(input.GetNodeId())
	if err != nil {
		return err
	}
	mounts, err := pathInput(input.GetPathContext())
	if err != nil {
		return err
	}
	archive, err := s.Store.OpenArchive(stream.Context(), fs, mounts, id)
	if err != nil {
		return err
	}
	defer archive.Close()
	result := make(chan error, 1)
	go func() {
		if err := stream.Send(&letfsv1.StreamArchiveResponse{Frame: &letfsv1.StreamArchiveResponse_Metadata{Metadata: &letfsv1.ArchiveMetadata{Filename: archive.Name, Mime: "application/zip"}}}); err != nil {
			result <- err
			return
		}
		buffer := make([]byte, 65536)
		for {
			n, err := archive.Read(buffer)
			if n > 0 {
				if sendErr := stream.Send(&letfsv1.StreamArchiveResponse{Frame: &letfsv1.StreamArchiveResponse_Data{Data: append([]byte(nil), buffer[:n]...)}}); sendErr != nil {
					result <- sendErr
					return
				}
			}
			if err != nil {
				if errors.Is(err, io.EOF) {
					err = nil
				}
				result <- err
				return
			}
		}
	}()
	// Returning on deadline terminates a transport-blocked Send; Close joins the ZIP producer.
	select {
	case <-archive.Context.Done():
		return status.FromContextError(archive.Context.Err()).Err()
	case err := <-result:
		if archive.Context.Err() != nil {
			return status.FromContextError(archive.Context.Err()).Err()
		}
		if err != nil && status.Code(err) == codes.Unknown {
			return rpc.Fault(codes.Internal, "ARCHIVE_FAILED", "archive stream failed")
		}
		return err
	}
}
