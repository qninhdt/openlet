from __future__ import annotations

from typing import TYPE_CHECKING

from letfs_ingest.index import index, points
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_api.letfs.v1 import letfs_pb2 as letfs

if TYPE_CHECKING:
    from collections.abc import Sequence

    from openlet_sdk.config import Config
    from qdrant_client import models


async def test_index_uses_content_scoped_payload_and_clears_old_blob_points(
    config: Config,
) -> None:
    deleted: list[tuple[str, models.PointsSelector, bool]] = []
    upserts: list[Sequence[models.PointStruct]] = []

    class FakeAI:
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.1, 0.2] for _ in texts]

    class FakeQdrant:
        async def delete(
            self,
            *,
            collection_name: str,
            points_selector: models.PointsSelector,
            wait: bool = True,
        ) -> None:
            deleted.append((collection_name, points_selector, wait))

        async def upsert(
            self,
            *,
            collection_name: str,
            points: Sequence[models.PointStruct],
            wait: bool = True,
        ) -> None:
            upserts.append(points)

    info = internal.GetBlobArtifactsResponse(
        workspace_id="ws-1",
        blob_id="blob-1",
        media_type="application/pdf",
        artifacts=[
            internal.BlobArtifact(
                id="a0",
                path="README.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content="# TOC",
                title="Annual Report",
                description="Full report index",
                indexable=False,  # skipped because split parts exist
            ),
            internal.BlobArtifact(
                id="a1",
                path="01-intro.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content="# Introduction\n\nSingle concise chunk of text.",
                title="Introduction",
                description="Opening findings.",
                indexable=True,
            ),
            internal.BlobArtifact(
                id="a2",
                path="tables/01-sales.csv",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/csv",
                text_content="Region,Revenue\nAPAC,250\n",
                title="Regional Revenue",
                description="Sales by region.",
                indexable=True,
            ),
            internal.BlobArtifact(
                id="a3",
                path="images/01-chart.png",
                kind=letfs.NODE_KIND_FILE,
                media_type="image/png",
                object_key="workspaces/ws-1/blobs/blob-1/artifacts/1",
                title="Growth Chart",
                description="Bar graph.",
                indexable=True,
            ),
        ],
    )

    generated = points(info, config)
    # 1-chunk markdown produces 1 point (NO duplicate summary vector), README skipped, 1 CSV + 1 image = 3 points.
    assert len(generated) == 3
    by_path = {p["artifact_path"]: (pid, p) for pid, p in generated}
    assert set(by_path) == {"01-intro.md", "tables/01-sales.csv", "images/01-chart.png"}
    assert set(by_path["01-intro.md"][1]) == {
        "workspace_id",
        "blob_id",
        "artifact_path",
        "kind",
        "title",
        "chunk_index",
        "text",
    }
    assert by_path["01-intro.md"][1]["kind"] == "text_chunk"
    assert by_path["tables/01-sales.csv"][1]["kind"] == "table"
    assert by_path["images/01-chart.png"][1]["kind"] == "image"
    assert "Columns: Region, Revenue" in by_path["tables/01-sales.csv"][1]["text"]

    await index(info, FakeAI(), FakeQdrant(), config)
    assert len(deleted) == 1
    assert len(upserts) == 1
    assert len(upserts[0]) == 3


def test_standalone_image_and_multichunk_markdown_points(config: Config) -> None:
    standalone = internal.GetBlobArtifactsResponse(
        workspace_id="ws-1",
        blob_id="blob-img",
        media_type="image/jpeg",
        title="System Diagram",
        description="End-to-end architecture diagram.",
        artifacts=[],
    )
    img_pts = points(standalone, config)
    assert len(img_pts) == 1
    assert img_pts[0][1]["artifact_path"] == ""
    assert img_pts[0][1]["kind"] == "image"

    long_md = "\n\n".join(
        f"Paragraph {i}: detailed evidence discussing financial growth metrics."
        for i in range(60)
    )
    multi = internal.GetBlobArtifactsResponse(
        workspace_id="ws-1",
        blob_id="blob-long",
        media_type="application/pdf",
        artifacts=[
            internal.BlobArtifact(
                id="p1",
                path="01-long.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content=long_md,
                title="Financial Growth",
                description="Long multi-chunk analysis.",
                indexable=True,
            )
        ],
    )
    multi_pts = points(multi, config)
    kinds = [p["kind"] for _, p in multi_pts]
    assert kinds[0] == "text"
    assert kinds.count("text_chunk") >= 2

    with_header = internal.GetBlobArtifactsResponse(
        workspace_id="ws-1",
        blob_id="blob-fm",
        media_type="application/pdf",
        artifacts=[
            internal.BlobArtifact(
                id="r1",
                path="README.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content=(
                    "# Doc Title\n\n"
                    "> Doc desc\n\n"
                    "## Images\n\n"
                    "- [Chart](images/01-fig.png) - Data\n\n"
                    "---\n\n"
                    "Actual body content.\n"
                ),
                title="Doc Title",
                description="Doc desc",
                indexable=True,
            )
        ],
    )
    hdr_pts = points(with_header, config)
    assert len(hdr_pts) == 1
    assert "## Images" not in hdr_pts[0][1]["text"]
    assert "Actual body content." in hdr_pts[0][1]["text"]
    assert hdr_pts[0][1]["text"].count("Doc Title") == 1

    workbook_readme = internal.GetBlobArtifactsResponse(
        workspace_id="ws-1",
        blob_id="blob-wb",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        artifacts=[
            internal.BlobArtifact(
                id="w1",
                path="README.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content=(
                    "# Sales Model\n\n"
                    "> Quarterly sales workbook.\n\n"
                    "## Sheet: Q1\n\n"
                    "- [Regional Sales (10x4)](tables/01-sales.csv) - Revenue by region.\n"
                ),
                title="Sales Model",
                description="Quarterly sales workbook.",
                indexable=True,
            )
        ],
    )
    wb_pts = points(workbook_readme, config)
    assert len(wb_pts) == 1
    assert "## Sheet: Q1" in wb_pts[0][1]["text"]
    assert wb_pts[0][1]["text"].count("Sales Model") == 1

    # Undersized trailing stub section folds cleanly into preceding chunk instead of producing a tiny stub point.
    stub_body = (
        "Substantive paragraph analyzing market trends and margins. " * 45
    ) + "\n\n## References:"
    with_stub = internal.GetBlobArtifactsResponse(
        workspace_id="ws-1",
        blob_id="blob-stub",
        media_type="application/pdf",
        artifacts=[
            internal.BlobArtifact(
                id="s1",
                path="01-report.md",
                kind=letfs.NODE_KIND_FILE,
                media_type="text/markdown",
                text_content=stub_body,
                title="Market Analysis",
                description="Trends and margin outlook.",
                indexable=True,
            )
        ],
    )
    stub_pts = points(with_stub, config)
    chunk_pts = [p for _, p in stub_pts if p["kind"] == "text_chunk"]
    assert all(len(p["text"]) >= 160 for p in chunk_pts)
    assert "## References:" in chunk_pts[-1]["text"]
