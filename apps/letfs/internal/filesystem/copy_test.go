package filesystem

import (
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func TestCopyDestinationMatchesStableReferenceIdentity(t *testing.T) {
	copyID := uuid.MustParse("00000000-0000-4000-8000-000000000001")
	source := uuid.MustParse("00000000-0000-4000-8000-000000000002")
	require.Equal(t, "557edf9b-0cdd-8e37-9245-847463184807", copyDestination(copyID, source).String())
	require.NotEqual(t, copyDestination(copyID, source), copyDestination(source, copyID))
}
