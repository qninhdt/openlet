package filesystem

import (
	"github.com/qninhdt/openlet/packages/go/apperr"
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func ptr[T any](v T) *T { return &v }

func reason(err error) string {
	if fault, ok := apperr.As(err); ok {
		return fault.Reason
	}
	return ""
}

func TestScopePathLimits(t *testing.T) {
	for _, path := range []string{"/", "/a/../Việt", "/a//./", "/" + strings.Repeat("a", 255)} {
		_, err := pathParts(Locator{Path: &path})
		require.NoError(t, err)
	}
	for _, path := range []string{"", "/\x00", "/" + strings.Repeat("a", 256), "/" + strings.Repeat("x/", 129), "/" + strings.Repeat("x", 4096)} {
		_, err := pathParts(Locator{Path: &path})
		require.Equal(t, "VALIDATION", reason(err))
	}
	id := uuid.New()
	for _, locator := range []Locator{{}, {NodeID: ptr(uuid.Nil)}, {NodeID: &id, Path: ptr("a")}, {NodeID: &id, CwdID: &id}, {Path: ptr("/a"), CwdID: &id}, {Path: ptr("a"), CwdID: ptr(uuid.Nil)}} {
		_, err := pathParts(locator)
		require.Equal(t, "VALIDATION", reason(err))
	}
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
		require.Equal(t, apperr.Invalid, apperr.KindOf(err))
	}
	_, _, err = page("scope", ptr("foreign|"+id.String()), nil)
	require.Equal(t, apperr.Invalid, apperr.KindOf(err))
	_, _, err = page("scope", ptr("scope|not-uuid"), nil)
	require.Equal(t, apperr.Invalid, apperr.KindOf(err))
}

func TestUserOperationsRequireVerifiedActorBeforeStorage(t *testing.T) {
	s := &Store{}
	_, err := s.GetNode(t.Context(), uuid.New(), Locator{})
	require.Equal(t, apperr.Unauthenticated, apperr.KindOf(err))
}
