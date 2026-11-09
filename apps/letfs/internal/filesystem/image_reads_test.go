package filesystem

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"hash/crc32"
	"image"
	"image/color"
	"image/png"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestImagePreviewBoundsPixelsAndReencodes(t *testing.T) {
	input := image.NewNRGBA(image.Rect(0, 0, 4096, 4))
	input.SetNRGBA(0, 0, color.NRGBA{R: 255, A: 255})
	var source bytes.Buffer
	require.NoError(t, png.Encode(&source, input))
	preview, err := imagePreview(t.Context(), bytes.NewReader(source.Bytes()))
	require.NoError(t, err)
	require.Equal(t, 2048, preview.Width)
	require.Equal(t, 2, preview.Height)
	decoded, err := png.Decode(bytes.NewReader(preview.Content))
	require.NoError(t, err)
	require.Equal(t, color.NRGBA{R: 255, A: 255}, color.NRGBAModel.Convert(decoded.At(0, 0)))
	digest := sha256.Sum256(preview.Content)
	require.Equal(t, hex.EncodeToString(digest[:]), preview.SHA256)
	// A valid header advertising a huge image must fail before allocating its pixels.
	bomb := bytes.Clone(source.Bytes())
	binary.BigEndian.PutUint32(bomb[16:20], 100000)
	binary.BigEndian.PutUint32(bomb[20:24], 100000)
	binary.BigEndian.PutUint32(bomb[29:33], crc32.ChecksumIEEE(bomb[12:29]))
	_, err = imagePreview(t.Context(), bytes.NewReader(bomb))
	require.Equal(t, "RESOURCE_LIMIT", reason(err))
	_, err = imagePreview(t.Context(), bytes.NewReader(source.Bytes()[:33]))
	require.Equal(t, "INVALID_IMAGE", reason(err))
	_, err = imagePreview(t.Context(), bytes.NewReader([]byte("not an image")))
	require.Equal(t, "UNSUPPORTED_IMAGE", reason(err))
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	_, err = imagePreview(ctx, bytes.NewReader(source.Bytes()))
	require.ErrorIs(t, err, context.Canceled)
	w := new(imageOutput)
	_, err = w.Write(make([]byte, MaxReadBytes+1))
	require.Equal(t, "RESOURCE_LIMIT", reason(err))
	require.Zero(t, w.Len())
}
