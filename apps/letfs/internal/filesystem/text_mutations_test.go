package filesystem

import (
	"math"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestTextMutationBytes(t *testing.T) {
	for _, tc := range []struct {
		name, before, after, reason string
		edit                        textMutation
	}{
		{name: "append CRLF", before: "chào\r\n", after: "chào\r\nnext  ", edit: textMutation{kind: "append", content: []byte("next  ")}},
		{name: "overwrite", before: "abcdef", after: "abXYef", edit: textMutation{kind: "offset", offset: 2, content: []byte("XY")}},
		{name: "extend", before: "ab", after: "abcd", edit: textMutation{kind: "offset", offset: 2, content: []byte("cd")}},
		{name: "gap", before: "ab", reason: "NOT_SUPPORTED", edit: textMutation{kind: "offset", offset: 3}},
		{name: "negative offset", reason: "VALIDATION", edit: textMutation{kind: "offset", offset: -1}},
		{name: "overflow", reason: "VALIDATION", edit: textMutation{kind: "offset", offset: math.MaxInt64, content: []byte("a")}},
		{name: "ambiguous", before: "aa aa", reason: "AMBIGUOUS_MATCH", edit: textMutation{kind: "literal", old: "aa", content: []byte("b")}},
		{name: "all nonoverlapping", before: "aaa", after: "ba", edit: textMutation{kind: "literal", old: "aa", content: []byte("b"), all: true}},
		{name: "no match", before: "a", reason: "NO_MATCH", edit: textMutation{kind: "literal", old: "b", content: []byte("b")}},
		{name: "empty match", before: "a", reason: "VALIDATION", edit: textMutation{kind: "literal"}},
		{name: "truncate", before: "chào", after: "ch", edit: textMutation{kind: "truncate", length: 2}},
		{name: "growth", before: "a", reason: "NOT_SUPPORTED", edit: textMutation{kind: "truncate", length: 2}},
		{name: "negative length", reason: "VALIDATION", edit: textMutation{kind: "truncate", length: -1}},
		{name: "split UTF8", before: "chào", reason: "VALIDATION", edit: textMutation{kind: "truncate", length: 3}},
		{name: "overwrite UTF8", before: "é", reason: "VALIDATION", edit: textMutation{kind: "offset", offset: 1, content: []byte("x")}},
		{name: "NUL", reason: "VALIDATION", edit: textMutation{kind: "write", content: []byte("a\x00b")}},
		{name: "invalid UTF8", reason: "VALIDATION", edit: textMutation{kind: "write", content: []byte{0xff}}},
		{name: "limit", before: "1234", reason: "REQUEST_LIMIT", edit: textMutation{kind: "append", content: []byte("56789")}},
		{name: "replace expansion", before: "aaaa", reason: "REQUEST_LIMIT", edit: textMutation{kind: "literal", old: "a", content: []byte("123"), all: true}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, err := tc.edit.apply([]byte(tc.before), 16)
			if tc.name == "limit" || tc.name == "replace expansion" {
				got, err = tc.edit.apply([]byte(tc.before), 8)
			}
			if tc.reason != "" {
				require.Equal(t, tc.reason, errorReason(err))
				return
			}
			require.NoError(t, err)
			require.Equal(t, tc.after, string(got))
		})
	}
}
