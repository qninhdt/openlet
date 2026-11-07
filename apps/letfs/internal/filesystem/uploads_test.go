package filesystem

import (
	"github.com/qninhdt/openlet/packages/go/apperr"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/qninhdt/openlet/apps/letfs/internal/clients/storage"
	"github.com/stretchr/testify/require"
)

func TestMultipartReceiptAndPartBounds(t *testing.T) {
	partSize := int64(5 * 1024 * 1024)
	for _, test := range []struct {
		size  int64
		count int32
	}{{0, 0}, {1, 1}, {partSize, 1}, {partSize + 1, 2}, {partSize * 10000, 10000}} {
		require.Equal(t, test.count, (Upload{SizeBytes: test.size, PartSize: &partSize}).PartCount())
	}
	require.NoError(t, multipartEvidence([]storage.PartReceipt{{Number: 1, ETag: "opaque-provider-validator"}}, 1))
	for _, parts := range [][]storage.PartReceipt{nil, {{Number: 2, ETag: "etag"}}, {{Number: 1, ETag: ""}}, {{Number: 1, ETag: "bad\r\n"}}, {{Number: 1, ETag: "unicode\u0085control"}}} {
		require.Error(t, multipartEvidence(parts, 1))
	}
	require.NoError(t, (Upload{State: "completing", ExpiresAt: time.Now().Add(time.Minute)}).active())
	for _, u := range []Upload{{State: "open", ExpiresAt: time.Now().Add(-time.Second)}, {State: "finalized", ExpiresAt: time.Now().Add(time.Minute)}, {State: "aborted", ExpiresAt: time.Now().Add(time.Minute)}} {
		require.Error(t, u.active())
	}
}

func TestUploadAdmissionPrecedesDependencies(t *testing.T) {
	s := &Store{}
	_, err := s.CreateUpload(t.Context(), uuid.New(), uuid.New(), UploadCreation{})
	require.Equal(t, apperr.Unauthenticated, apperr.KindOf(err))
	_, err = s.GetUpload(t.Context(), uuid.New(), uuid.New())
	require.Equal(t, apperr.Unauthenticated, apperr.KindOf(err))
	_, err = s.GetUploadParts(t.Context(), uuid.New(), uuid.New(), []int32{1})
	require.Equal(t, apperr.Unauthenticated, apperr.KindOf(err))
	_, err = s.CompleteUpload(t.Context(), uuid.New(), uuid.New(), nil)
	require.Equal(t, apperr.Unauthenticated, apperr.KindOf(err))
	require.Equal(t, apperr.Unauthenticated, apperr.KindOf(s.AbortUpload(t.Context(), uuid.New(), uuid.New())))
}
