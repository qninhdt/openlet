package storage

import (
	"bytes"
	"context"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	"image/png"
	"io"
	"strings"

	"github.com/aws/aws-sdk-go-v2/service/s3"
	pb "github.com/qninhdt/openlet/packages/sdk-go/gen/openlet_api/letfs/v1"
	"golang.org/x/image/draw"
	_ "golang.org/x/image/webp"
	"google.golang.org/genproto/googleapis/api/httpbody"
)

func (s *Server) ReadImage(ctx context.Context, r *pb.ReadImageRequest) (*httpbody.HttpBody, error) {
	if _, err := s.check(ctx, "storage", r.StorageId, "read"); err != nil {
		return nil, err
	}
	v, err := oneResolved(ctx, s.DB, r.WorkspaceId, r.StorageId, r.Target, true, false)
	if err != nil {
		return nil, err
	}
	if v.ObjectKey == nil || !strings.HasPrefix(v.Node.File.MediaType, "image/") {
		return nil, invalid("node is not a blob image")
	}
	object, err := s.S3.GetObject(ctx, &s3.GetObjectInput{Bucket: &s.Bucket, Key: v.ObjectKey})
	if err != nil {
		return nil, err
	}
	defer object.Body.Close()
	data, err := io.ReadAll(io.LimitReader(object.Body, s.Settings.MaxBlobBytes+1))
	if err != nil {
		return nil, err
	}
	if int64(len(data)) > s.Settings.MaxBlobBytes {
		return nil, invalid("image exceeds blob limit")
	}
	if r.MaxWidth == 0 && r.MaxHeight == 0 {
		return &httpbody.HttpBody{ContentType: v.Node.File.MediaType, Data: data}, nil
	}
	config, _, err := image.DecodeConfig(bytes.NewReader(data))
	if err != nil {
		return nil, invalid("unsupported image")
	}
	if int64(config.Width)*int64(config.Height)*4 > s.Settings.MaxBlobBytes {
		return nil, invalid("decoded image exceeds configured memory budget")
	}
	img, _, err := image.Decode(bytes.NewReader(data))
	if err != nil {
		return nil, invalid("invalid image")
	}
	width, height := config.Width, config.Height
	if r.MaxWidth > 0 && width > int(r.MaxWidth) {
		height = max(1, height*int(r.MaxWidth)/width)
		width = int(r.MaxWidth)
	}
	if r.MaxHeight > 0 && height > int(r.MaxHeight) {
		width = max(1, width*int(r.MaxHeight)/height)
		height = int(r.MaxHeight)
	}
	dst := image.NewRGBA(image.Rect(0, 0, width, height))
	draw.CatmullRom.Scale(dst, dst.Bounds(), img, img.Bounds(), draw.Src, nil)
	var out bytes.Buffer
	if err = png.Encode(&out, dst); err != nil {
		return nil, err
	}
	return &httpbody.HttpBody{ContentType: "image/png", Data: out.Bytes()}, nil
}
