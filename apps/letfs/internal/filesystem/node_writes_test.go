package filesystem

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestMediaTypeAndProcessingFormats(t *testing.T) {
	for _, value := range []string{"text/plain", "application/vnd.test+json", "text/plain; charset=utf-8"} {
		require.NoError(t, mediaType(value))
	}
	for _, value := range []string{"", "plain", "text/", "text/a/b", "text/plain\r\nX: y", "text/plain\x00", "te xt/plain"} {
		require.Equal(t, "VALIDATION", reason(mediaType(value)))
	}
	for _, test := range []struct {
		name, format string
		parse        bool
	}{
		{"Report.PDF", "pdf", true}, {"table.xlsx", "xlsx", true}, {"script.go", "text", false},
		{"DATA.CSV", "csv", false}, {"photo.JPEG", "image", false}, {"archive.zip", "", false}, {"README", "", false},
	} {
		format, parse := processingFormat(test.name)
		require.Equal(t, test.format, format, test.name)
		require.Equal(t, test.parse, parse, test.name)
	}
}
