from letfs_ingest.index import points
from letfs_ingest.providers import Metadata
from letfs_ingest.readme import render
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as pb


def test_index_uses_full_artifact_and_stable_versioned_ids():
    text = "beginning " + "middle evidence " * 1000 + " unique ending"
    source = internal.ProcessingInput(workspace_id="workspace", storage_id="storage", artifacts=[
        internal.ProcessingArtifact(path="README.md", node=pb.Node(id="node", file=pb.FileHeader(media_type="text/markdown")), text_content=text),
    ])
    settings = {"chunk_size_tokens": 100, "chunk_overlap_tokens": 10}
    embedding = {"model": "model", "dimensions": 3}
    identity = {"file_id": "source", "version": 1}
    first = list(points(source, identity, settings, embedding, "files"))
    assert first == list(points(source, identity, settings, embedding, "files"))
    assert len(first) > 2
    assert "unique ending" in first[-1][1]["text"]
    assert all(payload["source_version"] == 1 for _, payload in first)
    newer = list(points(source, {**identity, "version": 2}, settings, embedding, "files"))
    assert not {key for key, _ in first} & {key for key, _ in newer}


def test_index_keeps_ancestor_context_and_skips_generated_readme_listing():
    root = Metadata(title="Quarterly audit", description="Financial controls", semantic_type="document:report", context="Audit evidence")
    section = Metadata(title="Revenue", description="European sales", semantic_type="text:overview", context="Regional performance")
    source = internal.ProcessingInput(workspace_id="w", storage_id="s", artifacts=[
        internal.ProcessingArtifact(path="README.md", node=pb.Node(id="root", file=pb.FileHeader(media_type="text/markdown", metadata=pb.FileMetadata(**root.model_dump()))), text_content=render(root, "Root body", {"section/README.md": {"title": "GENERATED-LISTING-ONLY"}})),
        internal.ProcessingArtifact(path="section/README.md", node=pb.Node(id="section", file=pb.FileHeader(media_type="text/markdown", metadata=pb.FileMetadata(**section.model_dump()))), text_content="Section body"),
        internal.ProcessingArtifact(path="section/evidence.md", node=pb.Node(id="leaf", file=pb.FileHeader(media_type="text/markdown", metadata=pb.FileMetadata(title="Detailed ledger", context="Full account overview"))), text_content="retained content " * 100),
    ])
    result = list(points(source, {"file_id": "source", "version": 1}, {"chunk_size_tokens": 40, "chunk_overlap_tokens": 5}, {"model": "embed", "dimensions": 3}, "files"))
    assert all("GENERATED-LISTING-ONLY" not in payload["text"] for _, payload in result)
    leaf = [payload for _, payload in result if payload["file_id"] == "leaf"]
    assert leaf[0]["kind"] == "file" and "Full account overview" in leaf[0]["text"]
    assert all("Quarterly audit: Financial controls" in payload["text"] and "Revenue: European sales" in payload["text"] for payload in leaf)
    assert any(payload["kind"] == "chunk" and "retained content" in payload["text"] for payload in leaf)
