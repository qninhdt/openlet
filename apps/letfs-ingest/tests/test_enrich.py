import asyncio
import csv
import io
import json

import httpx
import pytest
from letfs_ingest.enrich import enrich
from letfs_ingest.naming import artifact_paths, rewrite_artifact_links
from letfs_ingest.providers import Metadata, Models, SemanticType
from letfs_ingest.readme import own_body
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as pb


def artifact(path: str, text: str | None = None) -> internal.ProcessingArtifact:
    node = pb.Node(
        id=path, kind=pb.NODE_KIND_DIRECTORY if text is None else pb.NODE_KIND_FILE
    )
    if text is not None:
        node.file.media_type = "text/csv" if path.endswith(".csv") else "text/markdown"
    return internal.ProcessingArtifact(path=path, node=node, text_content=text)


def test_names_reserve_siblings_and_keep_structure() -> None:
    items = [
        artifact("README.md", ""),
        artifact("1-part"),
        artifact("1-part/README.md", ""),
        artifact("1-part/1-body.md", ""),
        artifact("table-1.csv", ""),
        artifact("table-2.csv", ""),
        artifact("table-3.csv", ""),
    ]
    titles = ["Root", "unused", "Revenue", "Details", "Sales", "Sales", "Sales-2"]
    metadata = {
        item.path: Metadata(
            title=title,
            description="Evidence",
            semantic_type=SemanticType.TEXT_CONTENT,
            context="Report",
        )
        for item, title in zip(items, titles, strict=True)
    }
    paths = artifact_paths(items, metadata)
    assert paths == {
        "README.md": "README.md",
        "1-part": "1-revenue",
        "1-part/README.md": "1-revenue/README.md",
        "1-part/1-body.md": "1-revenue/1-details.md",
        "table-1.csv": "sales.csv",
        "table-2.csv": "sales-3.csv",
        "table-3.csv": "sales-2.csv",
    }
    assert artifact_paths(list(reversed(items)), metadata) == paths
    body = '[data](../table-1.csv?download=1#rows "Table") ![pic](<../table-2.csv>) [external](https://example.com/table-1.csv) [other](missing.md)'
    rewritten = rewrite_artifact_links(body, "1-part/1-body.md", paths)
    assert (
        rewritten
        == '[data](../sales.csv?download=1#rows "Table") ![pic](<../sales-3.csv>) [external](https://example.com/table-1.csv) [other](missing.md)'
    )
    metadata["table-1.csv"].title = "財" * 200
    assert len(artifact_paths(items, metadata)["table-1.csv"].encode()) <= 255
    metadata["table-1.csv"].title = "!!!"
    assert artifact_paths(items, metadata)["table-1.csv"] == "artifact.csv"


@pytest.mark.asyncio
async def test_enrichment_renames_tree_and_rewrites_all_markdown_without_extra_model_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("letfs_ingest.enrich.activity.heartbeat", lambda: None)
    items = [
        artifact("README.md", "[Part](1-part/README.md)"),
        artifact("1-part"),
        artifact("1-part/README.md", "[Body](1-body.md)"),
        artifact("1-part/1-body.md", "[Table](../table-1.csv)"),
        artifact("table-1.csv", "region,sales\nEU,42"),
    ]
    calls: list[str] = []
    titles = {
        "README.md": "Report",
        "1-part/README.md": "Revenue",
        "1-part/1-body.md": "Evidence",
        "table-1.csv": "Sales",
    }

    class TestModels(Models):
        def __init__(self) -> None:
            self.slots = asyncio.Semaphore(2)

        async def describe(
            self,
            name: str,
            text: str,
            media: str,
            children: str,
            image: bytes | None = None,
        ) -> Metadata:
            calls.append(name)
            return Metadata(
                title=titles[name],
                description="Useful evidence",
                semantic_type=SemanticType.TEXT_CONTENT,
                context="Annual report",
            )

    source = internal.ProcessingInput(source_name="original.pdf", artifacts=items)
    async with httpx.AsyncClient() as http:
        result = await enrich(
            source,
            {"file_id": "source", "version": 7},
            TestModels(),
            http,
            10000,
        )
    assert len(calls) == 4 and calls[-2:] == ["1-part/README.md", "README.md"]
    updates = {item.node_id: item for item in result.artifacts}
    assert updates["1-part"].name == "1-revenue" and not updates["1-part"].HasField(
        "metadata"
    )
    assert updates["1-part/1-body.md"].name == "1-evidence.md"
    assert updates["table-1.csv"].name == "sales.csv"
    assert not updates["README.md"].HasField("name")
    assert own_body(updates["README.md"].text_content) == "[Part](1-revenue/README.md)"
    assert own_body(updates["1-part/README.md"].text_content) == "[Body](1-evidence.md)"
    assert updates["1-part/1-body.md"].text_content == "[Table](../sales.csv)"
    header = json.loads(updates["README.md"].text_content.partition("\n---\n")[0][4:])
    assert set(header["children"]) == {"1-revenue/README.md", "sales.csv"}
    assert (
        result.source_metadata.title == "Report"
        and source.source_name == "original.pdf"
    )


def test_link_rewrite_preserves_literal_code_and_plain_csv_but_updates_rich_cells() -> (
    None
):
    from letfs_ingest.naming import table_metadata

    paths = {
        "README.md": "README.md",
        "image-1.png": "diagram.png",
        "table-1.csv": "data.csv",
    }
    code = "```python\n'[x](image-1.png)'\n```"
    plain = '<!-- artifact-table {"rich": false} -->\n\n```csv\n"[literal](image-1.png)",1\n```'
    rich = '<!-- artifact-table {"rich": true} -->\n\n```csv\n"![Image](image-1.png)","multiline\nvalue"\n```'
    inline = "Use `[literal](image-1.png)` as code. [actual](image-1.png)"
    body = code + "\n\n" + plain + "\n\n" + rich + "\n\n" + inline
    rewritten = rewrite_artifact_links(body, "README.md", paths)
    assert code in rewritten and plain in rewritten
    assert (
        "`[literal](image-1.png)`" in rewritten and "[actual](diagram.png)" in rewritten
    )
    assert '![Image](diagram.png),"multiline\nvalue"' in rewritten
    assert table_metadata(code) == []
    csv_body = '"![Image](image-1.png)","multiline\nvalue"\r\n'
    changed = rewrite_artifact_links(csv_body, "table-1.csv", paths, csv_cells=True)
    assert list(csv.reader(io.StringIO(changed, newline=""))) == [
        ["![Image](diagram.png)", "multiline\nvalue"]
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("inline_parent", [False, True])
async def test_enrichment_updates_external_rich_csv_links(
    monkeypatch: pytest.MonkeyPatch,
    inline_parent: bool,
) -> None:
    monkeypatch.setattr("letfs_ingest.enrich.activity.heartbeat", lambda: None)
    nested = '<!-- artifact-table {"rich": true, "parts": ["table-1.csv"]} -->\n\n[Table](table-1.csv)'
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerow([nested])
    parent = buffer.getvalue()
    root = (
        '<!-- artifact-table {"rich": true} -->\n\n```csv\n' + parent + "```"
        if inline_parent
        else '<!-- artifact-table {"rich": true, "parts": ["table-2.csv"]} -->\n\n[Table](table-2.csv)'
    )
    items = [
        artifact("README.md", root),
        artifact("table-2.csv", parent),
        artifact("table-1.csv", '"[Details](part-002.md)",123\n'),
        artifact("part-002.md", "Evidence"),
    ]

    class TestModels(Models):
        def __init__(self) -> None:
            self.slots = asyncio.Semaphore(2)

        async def describe(
            self,
            name: str,
            text: str,
            media: str,
            children: str,
            image: bytes | None = None,
        ) -> Metadata:
            return Metadata(
                title={
                    "README.md": "Report",
                    "table-1.csv": "Data",
                    "table-2.csv": "Outer",
                    "part-002.md": "Evidence",
                }[name],
                description="Useful",
                semantic_type=SemanticType.TEXT_CONTENT,
                context="Report",
            )

    async with httpx.AsyncClient() as http:
        result = await enrich(
            internal.ProcessingInput(artifacts=items),
            {"file_id": "source", "version": 1},
            TestModels(),
            http,
            10000,
        )
    updates = {item.node_id: item for item in result.artifacts}
    assert list(csv.reader(io.StringIO(updates["table-1.csv"].text_content))) == [
        ["[Details](evidence.md)", "123"]
    ]
    outer = updates["README.md" if inline_parent else "table-2.csv"].text_content
    assert "data.csv" in outer and "[Table](table-1.csv)" not in outer
