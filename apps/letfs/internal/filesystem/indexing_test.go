package filesystem

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestVectorSpaceValidation(t *testing.T) {
	require.NoError(t, (VectorSpace{Model: "provider/model", Collection: "files-v2_1", Dimension: 65536}).Validate())
	for _, space := range []VectorSpace{
		{Model: " ", Collection: "files", Dimension: 1536},
		{Model: "model", Collection: "", Dimension: 1536},
		{Model: "model", Collection: "../files", Dimension: 1536},
		{Model: "model", Collection: "filés", Dimension: 1536},
		{Model: "model", Collection: strings.Repeat("a", 101), Dimension: 1536},
		{Model: "model", Collection: "files", Dimension: 0},
		{Model: "model", Collection: "files", Dimension: 65537},
	} {
		require.Error(t, space.Validate())
	}
}
