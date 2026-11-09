package filesystem

import (
	"math"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestTextSelectionsPreserveExactBytes(t *testing.T) {
	body := []byte("\xef\xbb\xbfchào\r\n\nlast  ")
	for _, test := range []struct {
		selection TextSelection
		want      string
		offset    int64
	}{
		{TextSelection{Kind: "whole"}, string(body), 0},
		{TextSelection{Kind: "head", LineCount: 1}, "\xef\xbb\xbfchào\r\n", 0},
		{TextSelection{Kind: "head", LineCount: 0}, "", 0},
		{TextSelection{Kind: "tail", LineCount: 1}, "last  ", 11},
		{TextSelection{Kind: "tail", LineCount: 2}, "\nlast  ", 10},
		{TextSelection{Kind: "tail", LineCount: 99}, string(body), 0},
		{TextSelection{Kind: "tail", LineCount: 0}, "", 17},
		{TextSelection{Kind: "lines", StartLine: 2, LineCount: 1}, "\n", 10},
		{TextSelection{Kind: "lines", StartLine: 4, LineCount: 1}, "", 17},
		{TextSelection{Kind: "bytes", Offset: 3, Length: ptr(int64(2))}, "ch", 3},
		{TextSelection{Kind: "bytes", Offset: 6, Length: ptr(int64(1))}, string([]byte{0xa0}), 6},
		{TextSelection{Kind: "bytes", Offset: 99}, "", 17},
	} {
		require.NoError(t, test.selection.validate())
		got, offset := selectText(body, test.selection)
		require.Equal(t, []byte(test.want), got, "%+v", test.selection)
		require.Equal(t, test.offset, offset, "%+v", test.selection)
	}
	for _, body := range []string{"", "\n", "\na\n", "a\nb\n", "a\nb"} {
		got, _ := selectText([]byte(body), TextSelection{Kind: "tail", LineCount: 100})
		require.Equal(t, body, string(got))
	}
}

func TestTextSelectionValidation(t *testing.T) {
	for _, s := range []TextSelection{{}, {Kind: "bytes", Offset: -1}, {Kind: "bytes", Length: ptr(int64(-1))}, {Kind: "bytes", Offset: math.MaxInt64, Length: ptr(int64(1))}, {Kind: "lines", StartLine: 0}, {Kind: "lines", StartLine: math.MaxInt64, LineCount: 1}, {Kind: "head", LineCount: -1}, {Kind: "tail", LineCount: -1}} {
		require.Equal(t, "VALIDATION", reason(s.validate()))
	}
}
