package filesystem

import (
	"strings"
	"testing"

	"github.com/google/uuid"
	"github.com/stretchr/testify/require"
)

func TestSemanticMetadataTaxonomyAndBounds(t *testing.T) {
	valid := SemanticMetadata{Title: "Report", Description: "Own content.", SemanticType: "document:report", Context: "Evidence."}
	require.NoError(t, valid.validate())
	for _, kind := range []string{"report", "folder:part", "image:research_paper", "document:photo", "audio:other", "other:unknown:extra"} {
		invalid := valid
		invalid.SemanticType = kind
		require.Error(t, invalid.validate(), kind)
	}
	for _, text := range []string{"", " ", "a\x00b", strings.Repeat("x", 201), string([]byte{255})} {
		invalid := valid
		invalid.Title = text
		require.Error(t, invalid.validate())
	}
	valid.Title = strings.Repeat("ệ", 200)
	require.NoError(t, valid.validate(), "bounds count Unicode characters")
}

func TestEnrichmentManifestPreservesSourceAndTree(t *testing.T) {
	source, readme, folder, leaf := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	metadata := &SemanticMetadata{Title: "Report", Description: "Own content.", SemanticType: "document:report", Context: "Evidence."}
	rewrite := uuid.New()
	nodes := []ProcessingNode{
		{Node: Node{ID: source, Name: "report.pdf", Kind: "file"}},
		{Node: Node{ID: readme, ParentID: &source, Name: "README.md", Kind: "file"}, Path: "README.md"},
		{Node: Node{ID: folder, ParentID: &source, Name: "old", Kind: "directory"}, Path: "old"},
		{Node: Node{ID: leaf, ParentID: &folder, Name: "image.png", Kind: "file"}, Path: "old/image.png"},
	}
	valid := EnrichmentManifest{Nodes: []EnrichmentUpdate{{ID: source, Metadata: metadata}, {ID: readme, Path: "README.md", Metadata: metadata, UploadID: &rewrite}, {ID: folder, Path: "renamed"}, {ID: leaf, Path: "renamed/figure.png", Metadata: metadata}}}
	_, err := validateEnrichment(nodes, valid, source)
	require.NoError(t, err)
	for _, change := range []func(*EnrichmentManifest){
		func(m *EnrichmentManifest) { m.Nodes = m.Nodes[:3] },
		func(m *EnrichmentManifest) { m.Nodes[0].Path = "renamed.pdf" },
		func(m *EnrichmentManifest) { m.Nodes[0].UploadID = &rewrite },
		func(m *EnrichmentManifest) { m.Nodes[1].Path = "overview.md" },
		func(m *EnrichmentManifest) { m.Nodes[1].UploadID = nil },
		func(m *EnrichmentManifest) { m.Nodes[2].Metadata = metadata },
		func(m *EnrichmentManifest) { m.Nodes[3].Path = "figure.png" },
		func(m *EnrichmentManifest) { m.Nodes[3].Path = "renamed/figure.jpg" },
		func(m *EnrichmentManifest) { m.Nodes[3].ID = uuid.New() },
		func(m *EnrichmentManifest) { m.Nodes[3].Metadata = nil },
		func(m *EnrichmentManifest) { m.Nodes[3].UploadID = &rewrite },
	} {
		invalid := EnrichmentManifest{Nodes: append([]EnrichmentUpdate(nil), valid.Nodes...)}
		change(&invalid)
		_, err := validateEnrichment(nodes, invalid, source)
		require.Error(t, err)
	}
}
