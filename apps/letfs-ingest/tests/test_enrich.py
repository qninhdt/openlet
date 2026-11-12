import asyncio
import json
from types import SimpleNamespace

import pytest
from letfs_ingest.enrich import enrich
from letfs_ingest.naming import artifact_paths, rewrite_artifact_links
from letfs_ingest.providers import Metadata
from letfs_ingest.readme import own_body
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as pb


def artifact(path, text=None):
    node = pb.Node(id=path, kind=pb.NODE_KIND_DIRECTORY if text is None else pb.NODE_KIND_FILE)
    if text is not None:
        node.file.media_type = "text/csv" if path.endswith(".csv") else "text/markdown"
    return internal.ProcessingArtifact(path=path, node=node, text_content=text)


def test_names_reserve_siblings_and_keep_structure():
    items = [artifact("README.md", ""), artifact("1-part"), artifact("1-part/README.md", ""),
             artifact("1-part/1-body.md", ""), artifact("table-1.csv", ""),
             artifact("table-2.csv", ""), artifact("table-3.csv", "")]
    titles = ["Root", "unused", "Revenue", "Details", "Sales", "Sales", "Sales-2"]
    metadata = {item.path: SimpleNamespace(title=title) for item, title in zip(items, titles, strict=True)}
    paths = artifact_paths(items, metadata)
    assert paths == {
        "README.md": "README.md", "1-part": "1-revenue", "1-part/README.md": "1-revenue/README.md",
        "1-part/1-body.md": "1-revenue/1-details.md", "table-1.csv": "sales.csv",
        "table-2.csv": "sales-3.csv", "table-3.csv": "sales-2.csv",
    }
    assert artifact_paths(list(reversed(items)), metadata) == paths
    body = '[data](../table-1.csv?download=1#rows "Table") ![pic](<../table-2.csv>) [external](https://example.com/table-1.csv) [other](missing.md)'
    rewritten = rewrite_artifact_links(body, "1-part/1-body.md", paths)
    assert rewritten == '[data](../sales.csv?download=1#rows "Table") ![pic](<../sales-3.csv>) [external](https://example.com/table-1.csv) [other](missing.md)'
    metadata["table-1.csv"].title = "財" * 200
    assert len(artifact_paths(items, metadata)["table-1.csv"].encode()) <= 255
    metadata["table-1.csv"].title = "!!!"
    assert artifact_paths(items, metadata)["table-1.csv"] == "artifact.csv"


@pytest.mark.asyncio
async def test_enrichment_renames_tree_and_rewrites_all_markdown_without_extra_model_calls(monkeypatch):
    monkeypatch.setattr("letfs_ingest.enrich.activity.heartbeat", lambda: None)
    items = [artifact("README.md", "[Part](1-part/README.md)"), artifact("1-part"),
             artifact("1-part/README.md", "[Body](1-body.md)"),
             artifact("1-part/1-body.md", "[Table](../table-1.csv)"), artifact("table-1.csv", "region,sales\nEU,42")]
    calls = []
    titles = {"README.md": "Report", "1-part/README.md": "Revenue", "1-part/1-body.md": "Evidence", "table-1.csv": "Sales"}

    async def describe(path, body, media, summaries, image):
        calls.append(path)
        return Metadata(title=titles[path], description="Useful evidence", semantic_type="text:content", context="Annual report")

    source = internal.ProcessingInput(source_name="original.pdf", artifacts=items)
    result = await enrich(source, {"file_id": "source", "version": 7}, SimpleNamespace(slots=asyncio.Semaphore(2), describe=describe), None, 10000)
    assert len(calls) == 4 and calls[-2:] == ["1-part/README.md", "README.md"]
    updates = {item.node_id: item for item in result.artifacts}
    assert updates["1-part"].name == "1-revenue" and not updates["1-part"].HasField("metadata")
    assert updates["1-part/1-body.md"].name == "1-evidence.md"
    assert updates["table-1.csv"].name == "sales.csv"
    assert not updates["README.md"].HasField("name")
    assert own_body(updates["README.md"].text_content) == "[Part](1-revenue/README.md)"
    assert own_body(updates["1-part/README.md"].text_content) == "[Body](1-evidence.md)"
    assert updates["1-part/1-body.md"].text_content == "[Table](../sales.csv)"
    header = json.loads(updates["README.md"].text_content.partition("\n---\n")[0][4:])
    assert set(header["children"]) == {"1-revenue/README.md", "sales.csv"}
    assert result.source_metadata.title == "Report" and source.source_name == "original.pdf"
