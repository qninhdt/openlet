package letfs

import (
	"testing"

	"github.com/google/uuid"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/stretchr/testify/require"
)

func TestTextSearchValidatesCompleteResponse(t *testing.T) {
	scope, id := uuid.New(), uuid.New()
	valid := func() *letfsv1.TextSearchResponse {
		return &letfsv1.TextSearchResponse{Complete: true, Items: []*letfsv1.TreeEntry{{Path: "report.pdf/nested.md", Stat: &letfsv1.FileStat{Node: &letfsv1.Node{Id: id.String(), ScopeId: scope.String(), Kind: "file"}, RepresentationKind: "text", Fingerprint: "observed", ReadableSize: 20}}}}
	}
	options := TextSearchOptions{Mode: "files", Text: "needle"}
	result, err := nativeTextSearch(valid(), scope, Locator{}, options)
	require.NoError(t, err)
	require.Equal(t, "report.pdf/nested.md", result.Items[0].Path)
	for _, tc := range []struct {
		name string
		edit func(*letfsv1.TextSearchResponse)
	}{
		{"partial payload", func(v *letfsv1.TextSearchResponse) { v.Complete = false }},
		{"scope", func(v *letfsv1.TextSearchResponse) { v.Items[0].Stat.Node.ScopeId = uuid.NewString() }},
		{"path escape", func(v *letfsv1.TextSearchResponse) { v.Items[0].Path = "../secret" }},
		{"duplicate", func(v *letfsv1.TextSearchResponse) { v.Items = append(v.Items, v.Items[0]) }},
		{"wrong mode", func(v *letfsv1.TextSearchResponse) { v.Content = []byte("text") }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			v := valid()
			tc.edit(v)
			_, err := nativeTextSearch(v, scope, Locator{}, options)
			require.Error(t, err)
		})
	}
	_, err = nativeTextSearch(&letfsv1.TextSearchResponse{}, scope, Locator{}, options)
	require.NoError(t, err)
	v := valid()
	v.Stat, v.Items, v.Content = v.Items[0].Stat, nil, []byte("needle\r\n")
	options.Mode = "lines"
	result, err = nativeTextSearch(v, scope, Locator{NodeID: &id}, options)
	require.NoError(t, err)
	require.Equal(t, []byte("needle\r\n"), result.Content)
	v.Stat.Node.Id = uuid.NewString()
	_, err = nativeTextSearch(v, scope, Locator{NodeID: &id}, options)
	require.Error(t, err)
}
