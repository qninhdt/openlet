package filesystem

import (
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
	"google.golang.org/genproto/googleapis/rpc/errdetails"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

func ptr[T any](v T) *T { return &v }

func reason(err error) string {
	for _, detail := range status.Convert(err).Details() {
		if info, ok := detail.(*errdetails.ErrorInfo); ok {
			return info.Reason
		}
	}
	return ""
}

func TestPathMountBoundariesAndLimits(t *testing.T) {
	fs, other := uuid.New(), uuid.New()
	mounts := []Mount{{Path: "/drive", FilesystemID: fs}, {Path: "/drive/chat", FilesystemID: other}}
	for _, test := range []struct {
		path string
		want []string
		code string
	}{
		{"/drive/a/../Việt", []string{"a", "..", "Việt"}, ""},
		{"/drive//./", []string{}, ""},
		{"/drive/" + strings.Repeat("a", 255), []string{strings.Repeat("a", 255)}, ""},
		{"/driver/a", nil, "NOT_FOUND"},
		{"/drive/chat/a", nil, "CROSS_FILESYSTEM_UNSUPPORTED"},
		{"/drive/\x00", nil, "VALIDATION"},
		{"/drive/" + strings.Repeat("a", 256), nil, "VALIDATION"},
		{"/drive/" + strings.Repeat("x/", 129), nil, "VALIDATION"},
		{"/drive/" + strings.Repeat("x", 4096), nil, "VALIDATION"},
		{"", nil, "VALIDATION"},
	} {
		t.Run(test.path, func(t *testing.T) {
			parts, err := pathParts(fs, mounts, Locator{Path: &test.path})
			require.Equal(t, test.code, reason(err))
			if test.code == "" {
				require.NoError(t, err)
				require.Equal(t, test.want, parts)
			}
		})
	}
	for _, locator := range []Locator{{}, {NodeID: ptr(uuid.Nil)}, {NodeID: &fs, Path: ptr("a")}, {NodeID: &fs, CwdID: &fs}, {Path: ptr("/drive/a"), CwdID: &fs}, {Path: ptr("a"), CwdID: ptr(uuid.Nil)}} {
		_, err := pathParts(fs, mounts, locator)
		require.Equal(t, "VALIDATION", reason(err))
	}
	for _, mounts := range [][]Mount{nil, make([]Mount, 33), {{Path: "drive", FilesystemID: fs}}, {{Path: "/drive/", FilesystemID: fs}}, {{Path: "/drive/..", FilesystemID: fs}}, {{Path: "/drive", FilesystemID: fs}, {Path: "/drive", FilesystemID: other}}} {
		_, err := pathParts(fs, mounts, Locator{NodeID: &fs})
		require.Equal(t, "VALIDATION", reason(err))
	}
	parts, err := pathParts(fs, []Mount{{Path: "/", FilesystemID: fs}}, Locator{Path: ptr("/one")})
	require.NoError(t, err)
	require.Equal(t, []string{"one"}, parts)
}

func TestAliasGuardsAndScopedPages(t *testing.T) {
	id := uuid.New()
	for _, name := range []string{"@" + id.String(), "@" + strings.ToUpper(id.String())} {
		alias, ok := nodeAlias(name)
		require.True(t, ok)
		require.Equal(t, id, alias)
	}
	for _, name := range []string{"@notes", id.String(), "@" + strings.ReplaceAll(id.String(), "-", ""), "@{" + id.String() + "}"} {
		_, ok := nodeAlias(name)
		require.False(t, ok)
	}
	require.NoError(t, guard(Locator{NodeID: &id}, id, false))
	require.Equal(t, "PRECONDITION_REQUIRED", reason(guard(Locator{Path: ptr("/drive/a")}, id, true)))
	require.Equal(t, "TARGET_MISMATCH", reason(guard(Locator{Path: ptr("/drive/a"), ExpectedParentID: ptr(uuid.New())}, id, true)))
	require.NoError(t, guard(Locator{Path: ptr("/drive/a"), ExpectedParentID: &id}, id, true))
	_, count, err := page("scope", nil, nil)
	require.NoError(t, err)
	require.EqualValues(t, 50, count)
	for _, limit := range []int32{0, -1, 101} {
		_, _, err := page("scope", nil, &limit)
		require.Equal(t, codes.InvalidArgument, status.Code(err))
	}
	_, _, err = page("scope", ptr("foreign|"+id.String()), nil)
	require.Equal(t, codes.InvalidArgument, status.Code(err))
	_, _, err = page("scope", ptr("scope|not-uuid"), nil)
	require.Equal(t, codes.InvalidArgument, status.Code(err))
}

func TestUserOperationsRequireVerifiedActorBeforeStorage(t *testing.T) {
	s := &Store{}
	_, err := s.GetNode(t.Context(), uuid.New(), nil, Locator{})
	require.Equal(t, codes.Unauthenticated, status.Code(err))
}
