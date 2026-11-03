package main

import (
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func TestBackfillCommandDefaultsAndValidation(t *testing.T) {
	input, err := backfillOptions(nil)
	require.NoError(t, err)
	require.Nil(t, input)
	input, err = backfillOptions([]string{"--backfill-processing"})
	require.NoError(t, err)
	require.Equal(t, "missing", input.Mode)
	require.False(t, input.Apply)
	require.Equal(t, 100, input.Limit)
	require.Equal(t, uuid.Nil, input.After)
	after := uuid.New()
	input, err = backfillOptions([]string{"--backfill-processing", "--mode", "rebuild-index", "--apply", "--after", after.String(), "--limit", "1000"})
	require.NoError(t, err)
	require.True(t, input.Apply)
	require.Equal(t, "rebuild-index", input.Mode)
	require.Equal(t, after, input.After)
	require.Equal(t, 1000, input.Limit)
	for _, args := range [][]string{
		{"--unknown"}, {"--backfill-processing", "--unknown"}, {"--backfill-processing", "extra"},
		{"--backfill-processing", "--mode", "everything"}, {"--backfill-processing", "--mode"},
		{"--backfill-processing", "--limit", "0"}, {"--backfill-processing", "--limit", "1001"},
		{"--backfill-processing", "--after", "invalid"}, {"--backfill-processing", "--apply=maybe"},
	} {
		_, err = backfillOptions(args)
		require.Error(t, err, "%v", args)
	}
}
