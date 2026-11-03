package filesystem

import (
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func TestArtifactTreePathsCollisionsAndBounds(t *testing.T) {
	id := uuid.New()
	for _, path := range []string{"", "/a", "a/", "a//b", "../a", "a/./b", `a\b`, "a\x00b", strings.Repeat("a/", 128) + "b"} {
		require.Error(t, relativeArtifactPath(path), path)
	}
	for _, files := range []map[string]uuid.UUID{{"a": id, "a/b": id}, {"a/b/c": id, "a/b": id}} {
		_, err := outputTree(files, nil, 10)
		require.Error(t, err)
	}
	_, err := outputTree(map[string]uuid.UUID{"a": id}, []string{"a"}, 10)
	require.Error(t, err)
	_, err = outputTree(nil, []string{"empty", "empty"}, 10)
	require.Error(t, err)
	_, err = outputTree(map[string]uuid.UUID{"a/b": id}, nil, 1)
	require.Equal(t, "RESOURCE_LIMIT", errorReason(err))
	tree, err := outputTree(map[string]uuid.UUID{"sheet/table.csv": id}, []string{"sheet", "empty"}, 4)
	require.NoError(t, err)
	require.Len(t, tree, 3)
	require.Equal(t, id, *tree["sheet/table.csv"])
	require.Nil(t, tree["sheet"])
	require.Nil(t, tree["empty"])
	require.Equal(t, "text/csv", artifactMediaType("TABLE.CSV"))
	require.Equal(t, "text/plain", artifactMediaType("other.unknown"))
}
