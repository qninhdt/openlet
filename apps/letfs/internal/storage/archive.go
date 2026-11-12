package storage

import (
	"archive/zip"
	"buf.build/go/protovalidate"
	"context"
	"io"
	"mime"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/s3"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/genproto/googleapis/api/httpbody"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"
)

func (s *Server) GetDownload(ctx context.Context, r *pb.NodeRequest) (*pb.GetDownloadResponse, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	v, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Target, true, false)
	if err != nil {
		return nil, err
	}
	if v.Node.File == nil {
		return nil, status.Error(codes.FailedPrecondition, "download requires a file")
	}
	if v.Text != nil {
		return &pb.GetDownloadResponse{Download: &pb.GetDownloadResponse_Text{Text: &pb.TextDownload{Filename: v.Node.Name, MediaType: v.Node.File.MediaType, Content: *v.Text}}}, nil
	}
	disposition := mime.FormatMediaType("attachment", map[string]string{"filename": v.Node.Name})
	url, err := s.Presign.PresignGetObject(ctx, &s3.GetObjectInput{Bucket: &s.Bucket, Key: v.ObjectKey, ResponseContentDisposition: &disposition}, func(o *s3.PresignOptions) { o.Expires = time.Duration(s.Settings.DownloadURLTTLSeconds) * time.Second })
	if err != nil {
		return nil, err
	}
	return &pb.GetDownloadResponse{Download: &pb.GetDownloadResponse_Blob{Blob: &pb.SignedDownload{Url: url.URL, ExpiresAt: timestamppb.New(time.Now().Add(time.Duration(s.Settings.DownloadURLTTLSeconds) * time.Second))}}}, nil
}

type zipEntry struct {
	Name, Kind string
	Text, Key  *string
}
type bodyWriter struct {
	stream  grpc.ServerStreamingServer[httpbody.HttpBody]
	started bool
}

func (w *bodyWriter) Write(p []byte) (int, error) {
	total := len(p)
	for len(p) > 0 {
		n := min(len(p), 64*1024)
		msg := &httpbody.HttpBody{Data: append([]byte(nil), p[:n]...)}
		if !w.started {
			msg.ContentType = "application/zip"
			w.started = true
		}
		if err := w.stream.Send(msg); err != nil {
			return total - len(p), err
		}
		p = p[n:]
	}
	return total, nil
}
func (s *Server) DownloadArchive(r *pb.DownloadArchiveRequest, stream grpc.ServerStreamingServer[httpbody.HttpBody]) error {
	if err := protovalidate.Validate(r); err != nil {
		return invalid(err.Error())
	}
	ctx := stream.Context()
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return err
	}
	input, err := locatorJSON(r.Targets)
	if err != nil {
		return err
	}
	rows, err := s.DB.Query(ctx, resolverCTE+`,tree AS(SELECT n.id,n.kind,n.name AS path FROM resolved r JOIN nodes n ON n.id=r.id UNION ALL SELECT n.id,n.kind,CASE WHEN t.path='' THEN n.name ELSE t.path||'/'||n.name END FROM tree t JOIN nodes n ON n.parent_id=t.id WHERE t.kind='directory') SELECT DISTINCT ON(t.id) (SELECT count(*) FROM resolved),t.path,t.kind,f.text_content,f.object_key FROM tree t LEFT JOIN files f ON f.node_id=t.id ORDER BY t.id,t.path`, r.WorkspaceId, r.StorageId, input)
	if err != nil {
		return err
	}
	entries := []zipEntry{}
	var resolvedCount int
	names := map[string]bool{}
	for rows.Next() {
		var e zipEntry
		if err = rows.Scan(&resolvedCount, &e.Name, &e.Kind, &e.Text, &e.Key); err != nil {
			rows.Close()
			return err
		}
		if e.Name == "" {
			continue
		}
		if names[e.Name] {
			rows.Close()
			return invalid("selected files have duplicate archive paths")
		}
		names[e.Name] = true
		entries = append(entries, e)
	}
	rows.Close()
	if err = rows.Err(); err != nil {
		return err
	}
	if resolvedCount != len(r.Targets) {
		return notFound()
	}
	z := zip.NewWriter(&bodyWriter{stream: stream})
	for _, e := range entries {
		if e.Kind == "directory" {
			_, err = z.Create(e.Name + "/")
			if err != nil {
				return err
			}
			continue
		}
		w, err := z.Create(e.Name)
		if err != nil {
			return err
		}
		if e.Text != nil {
			if _, err = io.Copy(w, strings.NewReader(*e.Text)); err != nil {
				return err
			}
		} else {
			object, err := s.S3.GetObject(ctx, &s3.GetObjectInput{Bucket: &s.Bucket, Key: e.Key})
			if err != nil {
				return err
			}
			_, copyErr := io.Copy(w, object.Body)
			closeErr := object.Body.Close()
			if copyErr != nil {
				return copyErr
			}
			if closeErr != nil {
				return closeErr
			}
		}
	}
	return z.Close()
}
