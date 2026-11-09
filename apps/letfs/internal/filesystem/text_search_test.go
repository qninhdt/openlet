package filesystem

import (
	"bytes"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestLiteralSearchEscapesWildcards(t *testing.T) {
	require.Equal(t, `%a\%b\_c\\d%`, literalPattern(`a%b_c\d`))
}

func TestTextSearchKeepsAnIntactLongUnicodeLine(t *testing.T) {
	line := append(bytes.Repeat([]byte("dữ liệu "), 32768), []byte("needle\r\n")...)
	body := append([]byte("before\n"), line...)
	body = append(body, []byte("after")...)
	got, complete := candidateLines(body, "needle", false, 1, len(line))
	require.True(t, complete)
	require.Equal(t, line, got)
	got, complete = candidateLines(body, "needle", false, 1, len(line)-1)
	require.False(t, complete)
	require.Nil(t, got)
}

func TestTextSearchOriginalLines(t *testing.T) {
	body := []byte("first\r\nneedle twice needle\r\n\nlast needle")
	for _, tc := range []struct {
		name, text, want string
		ignore           bool
		lines, limit     int
		complete         bool
	}{
		{"literal", "needle", "needle twice needle\r\nlast needle", false, 10, 100, true},
		{"empty", "", string(body), false, 10, 100, true},
		{"ignore case safe superset", "NEEDLE", string(body), true, 10, 100, true},
		{"multiline safe superset", "first\r\nneedle", string(body), false, 10, 100, true},
		{"NUL", "\x00", "", false, 10, 100, true},
		{"no match", "absent", "", false, 10, 100, true},
		{"line bound", "needle", "", false, 1, 100, false},
		{"byte bound", "needle", "", false, 10, 5, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, complete := candidateLines(body, tc.text, tc.ignore, tc.lines, tc.limit)
			require.Equal(t, tc.complete, complete)
			require.Equal(t, tc.want, string(got))
		})
	}
}
