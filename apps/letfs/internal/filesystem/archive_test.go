package filesystem

import (
	"testing"

	"github.com/stretchr/testify/require"
)

func TestArchiveNamesRejectUnsafeAndAmbiguousPaths(t *testing.T) {
	for _, name := range []string{"", ".", "..", "a/b", `a\b`, "/root", "C:drive", "CON.txt", "lpt1", "a.", "a ", "x\ny", "a?b", "COM¹.txt", "LPT²", "com³.csv"} {
		require.Error(t, safeArchiveComponent(name), name)
	}
	for _, name := range []string{"Việt Nam", "report.pdf", "composition", "COM10.txt", "COMLPT1.txt"} {
		require.NoError(t, safeArchiveComponent(name), name)
	}
	require.Equal(t, archiveCollisionKey("Folder/É.txt"), archiveCollisionKey("folder/e\u0301.txt"))
	require.NotEqual(t, archiveCollisionKey("é.txt"), archiveCollisionKey("e.txt"))
}
