package filesystem

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestClassifyInlineText(t *testing.T) {
	s := Store{InlineLimit: 64, MaxFileBytes: 64}
	for _, test := range []struct {
		name, mime string
		content    []byte
		blobs      bool
		kind       string
	}{
		{"notes.txt", "text/plain", []byte("\xef\xbb\xbfXin chào 🌏\r\nlast  "), true, "text"},
		{"empty.txt", "text/plain", nil, true, "text"},
		{"config", "application/problem+json", []byte("{}"), true, "text"},
		{"main.go", "application/octet-stream", []byte("package main\n"), true, "text"},
		{"notes.txt", "text/plain", []byte{0xff}, true, "inline"},
		{"notes.txt", "text/plain", []byte("before\x00after"), true, "inline"},
		{"image.png", "text/plain", []byte("binary-looking-ascii"), true, "inline"},
		{"archive.zip", "text/plain", []byte("binary-looking-ascii"), true, "inline"},
		{"notes.txt", "image/png", []byte("binary-looking-ascii"), true, "inline"},
		{"raw.bin", "application/octet-stream", nil, true, "inline"},
		{"notes.pdf", "application/octet-stream", []byte("allowed text\n"), false, "text"},
	} {
		t.Run(test.name+"/"+test.mime+"/"+test.kind, func(t *testing.T) {
			payload := s.classifyInline(test.name, test.mime, test.content, test.blobs)
			require.Equal(t, test.kind, payload.Kind)
			if test.kind == "text" {
				require.NotNil(t, payload.Text)
				require.Equal(t, string(test.content), *payload.Text)
				require.Nil(t, payload.Bytes)
			} else {
				require.Equal(t, append([]byte{}, test.content...), payload.Bytes)
				require.Nil(t, payload.Text)
				require.Nil(t, payload.NewlineCount)
				require.Nil(t, payload.SHA256)
			}
		})
	}
	payload := s.classifyInline("notes.txt", "text/plain", []byte("hello\r\nworld\n"), true)
	require.EqualValues(t, 2, *payload.NewlineCount)
	// Independently calculated over the exact CRLF/LF bytes.
	require.Equal(t, "4375539f2263c313c68efccaa296d00e561e44e5cb4863dfffd2fed733a8bad8", *payload.SHA256)
}
