package grpc

import (
	"testing"

	"github.com/qninhdt/openlet/apps/letfs/internal/filesystem"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
)

func TestTextSearchSerializedLimitReturnsNoPartialPayload(t *testing.T) {
	value := filesystem.TextSearchResult{Complete: true, Content: []byte("needle\r\n"), Stat: &filesystem.FileStat{Fingerprint: "observed"}}
	full := textSearchMessage(value, 4096)
	limit := proto.Size(full)
	require.Equal(t, full, textSearchMessage(value, limit))
	for _, result := range []*filesystem.TextSearchResult{&value, {Complete: false, Content: value.Content, Stat: value.Stat}} {
		response := textSearchMessage(*result, limit-1)
		require.False(t, response.Complete)
		require.Empty(t, response.Content)
		require.Empty(t, response.Items)
		require.Nil(t, response.Stat)
	}
}
