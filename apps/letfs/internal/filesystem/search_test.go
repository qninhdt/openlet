package filesystem

import (
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func TestSearchBoundsAndCursorScope(t *testing.T) {
	for _, input := range []SearchInput{
		{Query: "words", Limit: ptr(int32(0))},
		{Query: "words", Sort: ptr("name;DROP TABLE nodes")},
		{Query: "words", Direction: ptr("descending")},
		{Query: "words", Filters: SearchFilters{CreatedAfter: ptr(time.Now().Add(time.Hour)), CreatedBefore: ptr(time.Now())}},
		{Query: strings.Repeat("x", 2001)}, {Query: "word\x00"},
	} {
		_, err := input.validate(false)
		require.Error(t, err)
	}
	_, err := (SearchInput{Query: " "}).validate(true)
	require.Error(t, err)
	_, err = (SearchInput{Query: "words", Limit: ptr(int32(51))}).validate(true)
	require.Error(t, err)
	value := searchCursor{Binding: "scope", Value: "file", ID: ptr(uuid.New())}
	encoded, err := encodeSearchCursor(value)
	require.NoError(t, err)
	decoded, err := decodeSearchCursor(encoded, "scope")
	require.NoError(t, err)
	require.Equal(t, value, decoded)
	_, err = decodeSearchCursor(encoded, "foreign")
	require.Error(t, err)
	_, err = decodeSearchCursor(ptr(strings.Repeat("A", 17000)), "scope")
	require.Error(t, err)
}
