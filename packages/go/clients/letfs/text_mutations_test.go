package letfs

import (
	"testing"

	"github.com/google/uuid"
	letfsv1 "github.com/qninhdt/openlet/packages/go/gen/openlet_api/letfs/v1"
	"github.com/stretchr/testify/require"
)

func TestTextMutationRejectsUnrelatedResponse(t *testing.T) {
	scope, id := uuid.New(), uuid.New()
	target := TextTarget{Locator: Locator{NodeID: &id}, Revision: 3}
	valid := func() *letfsv1.TextMutation {
		lf, sha := int64(0), "digest"
		return &letfsv1.TextMutation{Stat: &letfsv1.FileStat{Node: &letfsv1.Node{Id: id.String(), ScopeId: scope.String(), Kind: "file", Revision: 4}, StorageKind: "text", RepresentationKind: "text", Fingerprint: "after", NewlineCount: &lf, Sha256: &sha}, BeforeRevision: 3, BeforeFingerprint: "before"}
	}
	result, err := nativeTextMutation(valid(), scope, target)
	require.NoError(t, err)
	require.Equal(t, id, result.Stat.Node.ID)
	for _, tc := range []struct {
		name    string
		corrupt func(*letfsv1.TextMutation)
	}{
		{"foreign scope", func(v *letfsv1.TextMutation) { v.Stat.Node.ScopeId = uuid.NewString() }},
		{"replacement node", func(v *letfsv1.TextMutation) { v.Stat.Node.Id = uuid.NewString() }},
		{"wrong observation", func(v *letfsv1.TextMutation) { v.BeforeRevision = 2 }},
		{"stale result", func(v *letfsv1.TextMutation) { v.Stat.Node.Revision = 2 }},
		{"missing text metrics", func(v *letfsv1.TextMutation) { v.Stat.NewlineCount = nil }},
		{"blob response", func(v *letfsv1.TextMutation) { v.Stat.StorageKind = "object" }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			v := valid()
			tc.corrupt(v)
			_, err := nativeTextMutation(v, scope, target)
			require.Error(t, err)
		})
	}
	creation := TextTarget{Create: &TextCreation{NodeID: &id}}
	v := valid()
	v.BeforeRevision = 0
	v.BeforeFingerprint = ""
	_, err = nativeTextMutation(v, scope, creation)
	require.NoError(t, err)
	v.Stat.Node.Id = uuid.NewString()
	_, err = nativeTextMutation(v, scope, creation)
	require.Error(t, err)
}
