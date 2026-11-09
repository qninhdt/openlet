package filesystem

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"image"
	_ "image/gif"
	_ "image/jpeg"
	"image/png"
	"io"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/packages/go/apperr"
	"github.com/qninhdt/openlet/packages/go/authz"
)

type ImageRead struct {
	Stat          FileStat
	Content       []byte
	Width, Height int
	SHA256        string
}

type imageOutput struct{ bytes.Buffer }

func (w *imageOutput) Write(body []byte) (int, error) {
	if len(body) > MaxReadBytes-w.Len() {
		return 0, readLimit()
	}
	return w.Buffer.Write(body)
}

func imagePreview(ctx context.Context, source io.Reader) (ImageRead, error) {
	// Replay only the consumed header; original object bytes never need a full in-memory copy.
	var header bytes.Buffer
	config, format, err := image.DecodeConfig(io.TeeReader(source, &header))
	if err != nil {
		if ctx.Err() != nil {
			return ImageRead{}, ctx.Err()
		}
		if errors.Is(err, image.ErrFormat) {
			return ImageRead{}, apperr.New(apperr.Unsupported, "UNSUPPORTED_IMAGE", "unsupported image format")
		}
		return ImageRead{}, apperr.New(apperr.Invalid, "INVALID_IMAGE", "invalid image")
	}
	if format != "png" && format != "jpeg" && format != "gif" {
		return ImageRead{}, apperr.New(apperr.Unsupported, "UNSUPPORTED_IMAGE", "unsupported image format")
	}
	if config.Width < 1 || config.Height < 1 || int64(config.Width) > 40000000/int64(config.Height) {
		return ImageRead{}, readLimit()
	}
	if err = ctx.Err(); err != nil {
		return ImageRead{}, err
	}
	decoded, _, err := image.Decode(io.MultiReader(bytes.NewReader(header.Bytes()), source))
	if err != nil {
		if ctx.Err() != nil {
			return ImageRead{}, ctx.Err()
		}
		return ImageRead{}, apperr.New(apperr.Invalid, "INVALID_IMAGE", "invalid image")
	}
	bounds := decoded.Bounds()
	w, h := bounds.Dx(), bounds.Dy()
	if w < 1 || h < 1 || int64(w) > 40000000/int64(h) {
		return ImageRead{}, readLimit()
	}
	width, height := w, h
	if w > 2048 || h > 2048 {
		if w >= h {
			width = 2048
			height = max(1, h*2048/w)
		} else {
			height = 2048
			width = max(1, w*2048/h)
		}
	}
	out := image.NewNRGBA(image.Rect(0, 0, width, height))
	for y := range height {
		if err = ctx.Err(); err != nil {
			return ImageRead{}, err
		}
		for x := range width {
			out.Set(x, y, decoded.At(bounds.Min.X+x*w/width, bounds.Min.Y+y*h/height))
		}
	}
	encoded := new(imageOutput)
	if err = png.Encode(encoded, out); err != nil {
		return ImageRead{}, err
	}
	if err = ctx.Err(); err != nil {
		return ImageRead{}, err
	}
	body := encoded.Bytes()
	digest := sha256.Sum256(body)
	return ImageRead{Content: body, Width: width, Height: height, SHA256: hex.EncodeToString(digest[:])}, nil
}

func (s *Store) ReadImage(ctx context.Context, scopeID uuid.UUID, locator Locator, expected *string) (ImageRead, error) {
	if expected != nil && (len(*expected) == 0 || len(*expected) > 256) {
		return ImageRead{}, apperr.New(apperr.Invalid, "VALIDATION", "invalid fingerprint")
	}
	if _, err := s.authorize(ctx, scopeID, "scope", authz.ScopeReadContent); err != nil {
		return ImageRead{}, err
	}
	if s.ImageSlots == nil {
		return ImageRead{}, apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "image preview unavailable")
	}
	if !s.ImageSlots.TryAcquire(1) {
		return ImageRead{}, readLimit()
	}
	defer s.ImageSlots.Release(1)
	session, err := s.openSession(ctx, scopeID, false)
	if err != nil {
		return ImageRead{}, err
	}
	defer session.tx.Rollback(ctx)
	node, err := session.resolveOne(ctx, locator)
	if err != nil {
		return ImageRead{}, err
	}
	if locator.ExpectedNodeID != nil && *locator.ExpectedNodeID != node.ID {
		return ImageRead{}, apperr.New(apperr.Conflict, "TARGET_MISMATCH", "target mismatch")
	}
	if node.Kind != "file" {
		return ImageRead{}, apperr.New(apperr.Conflict, "NOT_FILE", "file required")
	}
	stat, _, err := session.fileRepresentation(ctx, node)
	if err != nil {
		return ImageRead{}, err
	}
	if expected != nil && *expected != stat.Fingerprint {
		return ImageRead{}, apperr.New(apperr.Conflict, "CONTENT_CHANGED", "file representation changed")
	}
	if node.SizeBytes < 0 || node.SizeBytes > s.MaxFileBytes {
		return ImageRead{}, readLimit()
	}
	var inline []byte
	var key *string
	err = session.tx.QueryRow(ctx, `SELECT COALESCE(inline_bytes,convert_to(text_content,'UTF8')),object_key FROM files WHERE node_id=$1`, node.ID).Scan(&inline, &key)
	if err != nil {
		return ImageRead{}, databaseError(err)
	}
	if err = session.tx.Commit(ctx); err != nil {
		return ImageRead{}, databaseError(err)
	}
	var source io.ReadCloser = io.NopCloser(bytes.NewReader(inline))
	if key != nil {
		if s.Storage == nil {
			return ImageRead{}, apperr.New(apperr.Unavailable, "DEPENDENCY_UNAVAILABLE", "object storage unavailable")
		}
		source, err = s.Storage.Open(ctx, *key)
		if err != nil {
			return ImageRead{}, storageError(ctx, err)
		}
	}
	defer source.Close()
	preview, err := imagePreview(ctx, io.LimitReader(source, node.SizeBytes+1))
	if err != nil {
		return ImageRead{}, err
	}
	current, err := s.Stat(ctx, scopeID, locator, true)
	if err != nil {
		return ImageRead{}, err
	}
	if current.Fingerprint != stat.Fingerprint {
		return ImageRead{}, apperr.New(apperr.Conflict, "CONTENT_CHANGED", "image source changed")
	}
	preview.Stat = current
	return preview, nil
}
