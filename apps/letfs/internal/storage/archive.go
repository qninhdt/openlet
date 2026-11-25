package storage

import (
	"archive/zip"
	"context"
	"io"
	"mime"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/jackc/pgx/v5"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"google.golang.org/genproto/googleapis/api/httpbody"
	"google.golang.org/grpc"
	"google.golang.org/grpc/metadata"
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
		return nil, invalid("directory cannot be downloaded directly")
	}
	if v.ObjectKey == nil {
		text := ""
		if v.Text != nil {
			text = *v.Text
		}
		return &pb.GetDownloadResponse{Download: &pb.GetDownloadResponse_Text{Text: &pb.TextDownload{
			Filename:  v.Node.Name,
			MediaType: v.Node.File.MediaType,
			Content:   text,
		}}}, nil
	}
	disposition := mime.FormatMediaType("attachment", map[string]string{"filename": v.Node.Name})
	url, err := s.Presign.PresignGetObject(ctx, &s3.GetObjectInput{Bucket: &s.Bucket, Key: v.ObjectKey, ResponseContentDisposition: &disposition}, func(o *s3.PresignOptions) {
		o.Expires = time.Duration(s.Settings.DownloadURLTTLSeconds) * time.Second
	})
	if err != nil {
		return nil, err
	}
	return &pb.GetDownloadResponse{Download: &pb.GetDownloadResponse_Blob{Blob: &pb.SignedDownload{
		Url:       url.URL,
		ExpiresAt: timestamppb.New(time.Now().Add(time.Duration(s.Settings.DownloadURLTTLSeconds) * time.Second)),
	}}}, nil
}

type zipEntry struct {
	Name string
	Kind string
	Key  *string
	Text *string
}

type bodyWriter struct {
	stream grpc.ServerStreamingServer[httpbody.HttpBody]
}

func (w *bodyWriter) Write(p []byte) (int, error) {
	total := len(p)
	for len(p) > 0 {
		chunk := p
		if len(chunk) > 65536 {
			chunk = chunk[:65536]
		}
		msg := &httpbody.HttpBody{ContentType: "application/zip", Data: append([]byte(nil), chunk...)}
		if err := w.stream.Send(msg); err != nil {
			return total - len(p), err
		}
		p = p[len(chunk):]
	}
	return total, nil
}

func (s *Server) DownloadArchive(r *pb.DownloadArchiveRequest, stream grpc.ServerStreamingServer[httpbody.HttpBody]) error {
	ctx := stream.Context()
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return err
	}
	tx, err := s.DB.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	resolvedTargets, err := resolve(ctx, tx, r.WorkspaceId, r.StorageId, r.Targets, true, false)
	if err != nil {
		return err
	}
	entries := []zipEntry{}
	seen := map[string]struct{}{}
	addEntry := func(e zipEntry) error {
		if e.Name == "" {
			return invalid("selected files have invalid archive paths")
		}
		if _, exists := seen[e.Name]; exists {
			return invalid("selected files have duplicate archive paths")
		}
		seen[e.Name] = struct{}{}
		entries = append(entries, e)
		return nil
	}

	for _, t := range resolvedTargets {
		if t.Node == nil {
			return notFound()
		}
		if t.Artifact != nil {
			baseName := artifactBaseName(t.Artifact.Path)
			if t.Artifact.Kind == "file" {
				if err = addEntry(zipEntry{Name: baseName, Kind: "file", Key: t.ObjectKey, Text: t.Text}); err != nil {
					return err
				}
				continue
			}
			if err = addEntry(zipEntry{Name: baseName, Kind: "directory"}); err != nil {
				return err
			}
			rows, err := tx.Query(ctx, `SELECT path,kind,object_key,text_content FROM blob_artifacts WHERE blob_id=$1 AND path LIKE $2 ESCAPE '\' ORDER BY path`, t.Artifact.BlobID, prefixPattern(t.Artifact.Path))
			if err != nil {
				return err
			}
			for rows.Next() {
				var cPath, kind string
				var key, text *string
				if err = rows.Scan(&cPath, &kind, &key, &text); err != nil {
					rows.Close()
					return err
				}
				rel := strings.TrimPrefix(cPath, t.Artifact.Path+"/")
				if err = addEntry(zipEntry{Name: baseName + "/" + rel, Kind: kind, Key: key, Text: text}); err != nil {
					rows.Close()
					return err
				}
			}
			err = rows.Err()
			rows.Close()
			if err != nil {
				return err
			}
			continue
		}

		rows, err := tx.Query(ctx, `WITH RECURSIVE tree AS (
			SELECT n.id,n.kind,n.name AS path FROM nodes n WHERE n.id=$1 AND n.storage_id=$2
			UNION ALL
			SELECT n.id,n.kind,CASE WHEN t.path='' THEN n.name ELSE t.path||'/'||n.name END
			FROM tree t JOIN nodes n ON n.parent_id=t.id WHERE t.kind='directory'
		) SELECT t.path,t.kind,b.object_key,f.text_content FROM tree t LEFT JOIN files f ON f.node_id=t.id LEFT JOIN blobs b ON b.id=f.blob_id ORDER BY t.path`, t.Node.Id, r.StorageId)
		if err != nil {
			return err
		}
		for rows.Next() {
			var e zipEntry
			if err = rows.Scan(&e.Name, &e.Kind, &e.Key, &e.Text); err != nil {
				rows.Close()
				return err
			}
			if e.Name == "" {
				continue
			}
			if err = addEntry(e); err != nil {
				rows.Close()
				return err
			}
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return err
		}
	}

	if err = stream.SendHeader(metadata.Pairs("content-disposition", `attachment; filename="Openlet files.zip"`)); err != nil {
		return err
	}
	z := zip.NewWriter(&bodyWriter{stream: stream})
	for _, e := range entries {
		if e.Kind == "directory" {
			if _, err = z.Create(e.Name + "/"); err != nil {
				return err
			}
			continue
		}
		w, err := z.Create(e.Name)
		if err != nil {
			return err
		}
		if e.Key == nil {
			text := ""
			if e.Text != nil {
				text = *e.Text
			}
			if _, err = io.Copy(w, strings.NewReader(text)); err != nil {
				return err
			}
			continue
		}
		object, err := s.S3.GetObject(ctx, &s3.GetObjectInput{Bucket: &s.Bucket, Key: e.Key})
		if err != nil {
			return err
		}
		_, err = io.Copy(w, object.Body)
		object.Body.Close()
		if err != nil {
			return err
		}
	}
	return z.Close()
}
