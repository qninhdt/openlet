from collections.abc import Sequence
from io import BytesIO
from typing import override

import pytest
from letfs_ingest.enrich import enrich
from letfs_ingest.naming import artifact_paths, rewrite_artifact_links, rich_csv_paths
from letfs_ingest.providers import ArtifactEnrichment, EnrichItem
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as letfs
from openlet_sdk.config import Config
from PIL import Image, ImageDraw


def _png_bytes() -> bytes:
    img = Image.new("RGB", (60, 60), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 50, 50], fill="green")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_names_preserve_numeric_prefix_and_deduplicate_siblings() -> None:
    mapping = artifact_paths(
        [
            "README.md",
            "01-part.md",
            "02-part.md",
            "images/01-img.png",
            "images/02-img.png",
        ],
        {
            "README.md": "ignored-readme",
            "01-part.md": "Q1 Summary",
            "02-part.md": "Q1 Summary",
            "images/01-img.png": "Margin Chart",
            "images/02-img.png": None,
        },
    )
    assert mapping == {
        "README.md": "README.md",
        "01-part.md": "01-q1-summary.md",
        "02-part.md": "02-q1-summary.md",
        "images/01-img.png": "images/01-margin-chart.png",
        "images/02-img.png": "images/02-img.png",
    }


def test_link_rewrite_preserves_code_and_plain_csv_but_updates_rich_cells() -> None:
    mapping = {
        "01-part.md": "01-summary.md",
        "images/01-img.png": "images/01-chart.png",
        "tables/01-table.csv": "tables/01-sales.csv",
    }
    md_text = (
        "# Heading\n\n"
        "See ![chart](images/01-img.png) and [table](tables/01-table.csv) and `images/01-img.png`.\n\n"
        "```md\n[keep](images/01-img.png)\n```\n"
    )
    assert rich_csv_paths({"01-part.md": md_text}) == {"tables/01-table.csv"}
    rewritten_md = rewrite_artifact_links(
        md_text, "01-summary.md", "text/markdown", mapping
    )
    assert "![chart](images/01-chart.png)" in rewritten_md
    assert "[table](tables/01-sales.csv)" in rewritten_md
    assert "`images/01-img.png`" in rewritten_md
    assert "[keep](images/01-img.png)" in rewritten_md

    csv_body = 'metric,link\n"Margin Trend","[view](../images/01-img.png)"\n'
    rewritten_rich = rewrite_artifact_links(
        csv_body,
        "tables/01-sales.csv",
        "text/csv",
        mapping,
        is_rich_csv=True,
    )
    assert "[view](../images/01-chart.png)" in rewritten_rich

    plain_csv = 'note\n"[literal](../images/01-img.png)"\n'
    assert (
        rewrite_artifact_links(
            plain_csv, "tables/01-sales.csv", "text/csv", mapping, is_rich_csv=False
        )
        == plain_csv
    )


async def test_enrichment_batches_all_artifacts_and_rewrites_links(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[internal.SaveEnrichedArtifactsRequest] = []
    batched_items: list[list[EnrichItem]] = []

    class FakeS3:
        async def get_bytes(self, key: str, limit: int) -> bytes:
            assert key == "workspaces/ws-1/blobs/blob-1/artifacts/img"
            return _png_bytes()

    class FakeStub:
        async def SaveEnrichedArtifacts(
            self, req: internal.SaveEnrichedArtifactsRequest
        ) -> internal.BlobProcessingOutcome:
            saved.append(req)
            return internal.BlobProcessingOutcome(obsolete=False, stage="enriched")

    class FakeModels:
        async def describe_batch(
            self, items: Sequence[EnrichItem]
        ) -> dict[str, ArtifactEnrichment]:
            batched_items.append(list(items))
            return {
                "README.md": ArtifactEnrichment(
                    id="README.md",
                    title="Quarterly Report",
                    description="Q1 financials",
                ),
                "01-part.md": ArtifactEnrichment(
                    id="01-part.md",
                    title="Executive Summary",
                    description="Key highlights",
                    slug="executive-summary",
                ),
                "images/01-img.png": ArtifactEnrichment(
                    id="images/01-img.png",
                    title="Revenue Chart",
                    description="Quarterly bar chart",
                    slug="revenue-chart",
                ),
            }

    info = internal.GetBlobArtifactsResponse(
        outcome=internal.BlobProcessingOutcome(stage="parsed"),
        workspace_id="ws-1",
        blob_id="blob-1",
        media_type="application/pdf",
        artifacts=[
            internal.BlobArtifact(
                id="id-readme",
                blob_id="blob-1",
                path="README.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content="See [Summary](01-part.md)",
            ),
            internal.BlobArtifact(
                id="id-part1",
                blob_id="blob-1",
                path="01-part.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content="# Intro\n\n![Chart](images/01-img.png)",
                indexable=True,
            ),
            internal.BlobArtifact(
                id="id-img1",
                blob_id="blob-1",
                path="images/01-img.png",
                kind=letfs.NODE_KIND_FILE,
                media_type="image/png",
                object_key="workspaces/ws-1/blobs/blob-1/artifacts/img",
                indexable=True,
            ),
        ],
    )
    await enrich(info, FakeStub(), FakeS3(), FakeModels(), config)

    assert len(batched_items) == 1
    assert len(batched_items[0]) == 3
    assert len(saved) == 1
    req = saved[0]
    assert req.blob_title == "Quarterly Report"
    assert req.blob_description == "Q1 financials"
    by_id = {a.artifact_id: a for a in req.artifacts}
    readme_out = by_id["id-readme"].text_content
    assert readme_out.startswith("# Quarterly Report\n\n> Q1 financials\n\n")
    assert not readme_out.startswith("---\n")
    assert (
        "- [Revenue Chart](images/01-revenue-chart.png) - Quarterly bar chart"
        in readme_out
    )
    assert (
        "- [Executive Summary](01-executive-summary.md) - Key highlights" in readme_out
    )
    assert readme_out.endswith("\n---\n\nSee [Summary](01-executive-summary.md)\n")
    assert by_id["id-part1"].path == "01-executive-summary.md"
    assert (
        by_id["id-part1"].text_content
        == "# Intro\n\n![Chart](images/01-revenue-chart.png)"
    )
    assert by_id["id-img1"].path == "images/01-revenue-chart.png"

    # Multi-part TOC README replaces # Document Sections with # Title / > Description / ## Sections and inline descriptions.
    toc_info = internal.GetBlobArtifactsResponse(
        outcome=internal.BlobProcessingOutcome(stage="parsed"),
        workspace_id="ws-1",
        blob_id="blob-2",
        media_type="application/pdf",
        artifacts=[
            internal.BlobArtifact(
                id="id-readme",
                blob_id="blob-2",
                path="README.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content="# Document Sections\n\n- [Repeated Doc Title](01-part.md)\n",
            ),
            internal.BlobArtifact(
                id="id-part1",
                blob_id="blob-2",
                path="01-part.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content="# Intro\n\nBody",
                indexable=True,
            ),
            internal.BlobArtifact(
                id="id-img1",
                blob_id="blob-2",
                path="images/01-img.png",
                kind=letfs.NODE_KIND_FILE,
                media_type="image/png",
                object_key="workspaces/ws-1/blobs/blob-1/artifacts/img",
                indexable=True,
            ),
        ],
    )
    saved.clear()
    await enrich(toc_info, FakeStub(), FakeS3(), FakeModels(), config)
    toc_readme = {a.artifact_id: a for a in saved[0].artifacts}[
        "id-readme"
    ].text_content
    assert toc_readme == (
        "# Quarterly Report\n\n"
        "> Q1 financials\n\n"
        "## Sections\n\n"
        "- [Executive Summary](01-executive-summary.md) - Key highlights\n\n"
        "## Images\n\n"
        "- [Revenue Chart](images/01-revenue-chart.png) - Quarterly bar chart\n"
    )

    # Workbook README keeps sheet grouping, preserves table dims, and turns image bullets into linked descriptions.
    wb_info = internal.GetBlobArtifactsResponse(
        outcome=internal.BlobProcessingOutcome(stage="parsed"),
        workspace_id="ws-1",
        blob_id="blob-3",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        artifacts=[
            internal.BlobArtifact(
                id="id-readme",
                blob_id="blob-3",
                path="README.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content=(
                    "# Workbook Index\n\n"
                    "## Sheet: Summary\n\n"
                    "- [Raw Table (10x4)](tables/01-table.csv)\n"
                    "- ![Sheet image 1](images/01-img.png)\n"
                ),
            ),
            internal.BlobArtifact(
                id="id-tbl",
                blob_id="blob-3",
                path="tables/01-table.csv",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/csv",
                text_content="A,B\n1,2\n",
                indexable=True,
            ),
            internal.BlobArtifact(
                id="id-img1",
                blob_id="blob-3",
                path="images/01-img.png",
                kind=letfs.NODE_KIND_FILE,
                media_type="image/png",
                object_key="workspaces/ws-1/blobs/blob-1/artifacts/img",
                indexable=True,
            ),
        ],
    )

    class FakeWorkbookModels(FakeModels):
        @override
        async def describe_batch(
            self, items: Sequence[EnrichItem]
        ) -> dict[str, ArtifactEnrichment]:
            return {
                "README.md": ArtifactEnrichment(
                    id="README.md",
                    title="Q1 Financial Model",
                    description="Workbook summarizing Q1 revenue and charts.",
                ),
                "tables/01-table.csv": ArtifactEnrichment(
                    id="tables/01-table.csv",
                    title="Quarterly Revenue",
                    description="Revenue by region for Q1.",
                    slug="quarterly-revenue",
                ),
                "images/01-img.png": ArtifactEnrichment(
                    id="images/01-img.png",
                    title="Revenue Chart",
                    description="Quarterly bar chart",
                    slug="revenue-chart",
                ),
            }

    saved.clear()
    await enrich(wb_info, FakeStub(), FakeS3(), FakeWorkbookModels(), config)
    wb_readme = {a.artifact_id: a for a in saved[0].artifacts}["id-readme"].text_content
    assert wb_readme == (
        "# Q1 Financial Model\n\n"
        "> Workbook summarizing Q1 revenue and charts.\n\n"
        "## Sheet: Summary\n\n"
        "- [Quarterly Revenue (10x4)](tables/01-quarterly-revenue.csv) - Revenue by region for Q1.\n"
        "- [Revenue Chart](images/01-revenue-chart.png) - Quarterly bar chart\n"
    )

    # Single-file README (no children) still renders # Title / > Description / --- before body.
    single_info = internal.GetBlobArtifactsResponse(
        outcome=internal.BlobProcessingOutcome(stage="parsed"),
        workspace_id="ws-1",
        blob_id="blob-4",
        media_type="application/pdf",
        artifacts=[
            internal.BlobArtifact(
                id="id-readme",
                blob_id="blob-4",
                path="README.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content="Memo body text.\n",
                indexable=True,
            ),
        ],
    )

    class FakeSingleModels(FakeModels):
        @override
        async def describe_batch(
            self, items: Sequence[EnrichItem]
        ) -> dict[str, ArtifactEnrichment]:
            return {
                "README.md": ArtifactEnrichment(
                    id="README.md",
                    title="Project Mandate",
                    description="Client memo outlining scope.",
                ),
            }

    saved.clear()
    await enrich(single_info, FakeStub(), FakeS3(), FakeSingleModels(), config)
    single_readme = {a.artifact_id: a for a in saved[0].artifacts}[
        "id-readme"
    ].text_content
    assert single_readme == (
        "# Project Mandate\n\n"
        "> Client memo outlining scope.\n\n"
        "---\n\n"
        "Memo body text.\n"
    )


async def test_standalone_image_enriches_directly_on_blob(config: Config) -> None:
    saved: list[internal.SaveEnrichedArtifactsRequest] = []

    class FakeS3:
        async def get_bytes(self, key: str, limit: int) -> bytes:
            assert key == "workspaces/ws-1/blobs/blob-img/source"
            return _png_bytes()

    class FakeStub:
        async def SaveEnrichedArtifacts(
            self, req: internal.SaveEnrichedArtifactsRequest
        ) -> internal.BlobProcessingOutcome:
            saved.append(req)
            return internal.BlobProcessingOutcome(obsolete=False, stage="enriched")

    class FakeModels:
        async def describe_batch(
            self, items: Sequence[EnrichItem]
        ) -> dict[str, ArtifactEnrichment]:
            assert (
                len(items) == 1
                and items[0].id == "."
                and items[0].image_b64 is not None
            )
            return {
                ".": ArtifactEnrichment(
                    id=".",
                    title="System Diagram",
                    description="Microservice architecture flow.",
                )
            }

    info = internal.GetBlobArtifactsResponse(
        outcome=internal.BlobProcessingOutcome(stage="parsed"),
        workspace_id="ws-1",
        blob_id="blob-img",
        object_key="workspaces/ws-1/blobs/blob-img/source",
        media_type="image/png",
        artifacts=[],
    )
    await enrich(info, FakeStub(), FakeS3(), FakeModels(), config)
    assert len(saved) == 1
    assert saved[0].blob_title == "System Diagram"
    assert saved[0].blob_description == "Microservice architecture flow."
    assert len(saved[0].artifacts) == 0
