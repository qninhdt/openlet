import base64
import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from datalab_sdk import DatalabAPIError, DatalabAuthenticationError  # pyright: ignore[reportMissingTypeStubs]
from letfs_ingest.convert import DOCX_MEDIA, PPTX_MEDIA
from letfs_ingest.datalab import export
from letfs_ingest.parse import Parser
from letfs_ingest.storage import S3Store
from openlet_api.letfs.v1 import internal_pb2 as internal
from openlet_sdk.config import Config
from PIL import Image, ImageDraw
from temporalio.exceptions import ApplicationError


def _textured_b64(accent: str = "blue") -> str:
    img = Image.new("RGB", (100, 80), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([15, 15, 85, 65], fill=accent)
    draw.line([(0, 0), (100, 80)], fill="black", width=2)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _small_b64(size: tuple[int, int] = (12, 12), color: str = "black") -> str:
    img = Image.new("RGB", size, color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_datalab_export_filters_noise_and_deduplicates_images(
    tmp_path: Path, config: Config
) -> None:
    chart_b64 = _textured_b64()
    resp = tmp_path / "resp.json"
    resp.write_text(
        json.dumps(
            {
                "success": True,
                "page_count": 2,
                "markdown": (
                    "# Annual Report\n\n"
                    "![Revenue chart figure](fig1.png)\n\n"
                    "Revenue chart figure\n\n"
                    "![Duplicate chart](fig1_dup.png)\n\n"
                    "![Decorative Icon](tiny.png)\n\n"
                    "Decorative Icon\n\n"
                    "![Header Logo](hdr.png)\n\n"
                    "<!-- BEGIN IMAGE CAPTION -->\nSynthetic chart table\n<!-- END IMAGE CAPTION -->\n"
                ),
                "images": {
                    "fig1.png": chart_b64,
                    "fig1_dup.png": chart_b64,
                    "tiny.png": _small_b64((64, 64), color="blue"),
                    "hdr.png": _textured_b64("gray"),
                },
                "chunks": {
                    "blocks": [
                        {"block_type": "PageHeader", "images": {"hdr.png": True}},
                    ]
                },
            }
        )
    )
    out = tmp_path / "out"
    export(resp, True, out, config)

    readme = (out / "README.md").read_text()
    assert "![Revenue chart figure](images/01-img.png)" in readme
    assert "![Duplicate chart](images/01-img.png)" in readme
    assert readme.count("Revenue chart figure") == 1
    assert "Decorative Icon" not in readme
    assert "tiny.png" not in readme
    assert "hdr.png" not in readme
    assert "Synthetic chart table" not in readme
    saved = list((out / "images").glob("*"))
    assert len(saved) == 1 and saved[0].name == "01-img.png"


async def test_parser_saves_artifacts_and_uploads_images_to_s3(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploads: dict[str, tuple[bytes, str]] = {}
    saved_req: list[internal.SaveParsedArtifactsRequest] = []

    class FakeS3:
        async def download_to_file(self, key: str, target: Path, limit: int) -> int:
            assert key == "workspaces/ws-1/blobs/blob-1/source"
            target.write_bytes(b"fake-docx")
            return 9

        async def put_bytes(self, key: str, data: bytes, media_type: str) -> str:
            uploads[key] = (data, media_type)
            return "crc=="

    class FakeStub:
        async def GetBlobArtifacts(
            self, req: internal.BlobRequest
        ) -> internal.GetBlobArtifactsResponse:
            return internal.GetBlobArtifactsResponse(
                outcome=internal.BlobProcessingOutcome(obsolete=False, stage="queued"),
                workspace_id="ws-1",
                blob_id=req.blob_id,
                object_key="workspaces/ws-1/blobs/blob-1/source",
                source_download_url="https://s3.example/presigned",
                media_type=DOCX_MEDIA,
                source_name="C:/Users/Alice/report.docx",
            )

        async def SaveParsedArtifacts(
            self, req: internal.SaveParsedArtifactsRequest
        ) -> internal.BlobProcessingOutcome:
            saved_req.append(req)
            return internal.BlobProcessingOutcome(obsolete=False, stage="parsed")

    class FakeResult:
        success = True

    class FakeDatalab:
        async def convert(
            self,
            *,
            file_url: str | None,
            file_path: Path | None,
            options: object,
            stream_response_to: Path,
        ) -> FakeResult:
            assert file_url == "https://s3.example/presigned"
            assert file_path is None
            stream_response_to.write_text(
                json.dumps(
                    {
                        "success": True,
                        "page_count": 1,
                        "markdown": "# Doc\n\n![Chart](chart.png)\n",
                        "images": {"chart.png": _textured_b64()},
                    }
                )
            )
            return FakeResult()

    def _noop_preflight(*args: object) -> None:
        return None

    def _noop_hb(*args: object) -> None:
        return None

    monkeypatch.setattr("letfs_ingest.parse.preflight", _noop_preflight)
    monkeypatch.setattr("letfs_ingest.telemetry.activity.heartbeat", _noop_hb)
    parser = Parser(
        cast(Any, FakeStub()),
        cast(S3Store, FakeS3()),
        config,
        cast(Any, FakeDatalab()),
    )
    await parser.run("blob-1")

    assert len(uploads) == 1
    assert len(saved_req) == 1
    paths = {a.path: a for a in saved_req[0].artifacts}
    assert set(paths) == {"README.md", "images/01-img.png"}
    assert paths["README.md"].indexable is True
    assert paths["images/01-img.png"].indexable is True
    assert paths["images/01-img.png"].object_key.startswith(
        "workspaces/ws-1/blobs/blob-1/artifacts/"
    )
    _ = PPTX_MEDIA


def _raster_icon_b64(size: tuple[int, int], rows_of_noise: int = 8) -> str:
    w, h = size
    raw = bytearray(w * h)
    for y in range(min(h, rows_of_noise)):
        for x in range(w):
            digest = hashlib.sha256(f"{x}:{y}".encode()).digest()
            raw[y * w + x] = digest[0]
    img = Image.frombytes("L", size, bytes(raw)).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_datalab_drops_small_raster_icons_and_two_para_echoed_captions(
    tmp_path: Path, config: Config
) -> None:
    small_icon = _raster_icon_b64((140, 140), rows_of_noise=10)
    real_chart = _raster_icon_b64((400, 300), rows_of_noise=35)
    assert 1_200 < len(base64.b64decode(small_icon)) < 7_000
    assert len(base64.b64decode(real_chart)) >= 7_000

    resp = tmp_path / "resp.json"
    resp.write_text(
        json.dumps(
            {
                "success": True,
                "page_count": 2,
                "markdown": (
                    "# Report\n\n"
                    "![Annual growth overview](chart.png)\n\n"
                    "Bar graph illustrates revenue trends across regions.\n\n"
                    "Annual growth overview\n\n"
                    "Real concluding body paragraph.\n\n"
                    "![Small decorative badge](badge.png)\n\n"
                    "Small decorative badge\n"
                ),
                "images": {"chart.png": real_chart, "badge.png": small_icon},
            }
        )
    )
    out = tmp_path / "out"
    export(resp, True, out, config)

    readme = (out / "README.md").read_text()
    assert "![Annual growth overview](images/01-img.png)" in readme
    assert "Bar graph illustrates revenue trends across regions." in readme
    assert readme.count("Annual growth overview") == 1
    assert "Real concluding body paragraph." in readme
    assert "Small decorative badge" not in readme
    assert [p.name for p in (out / "images").glob("*")] == ["01-img.png"]


async def test_parser_retries_transient_datalab_errors_and_stops_on_permanent(
    tmp_path: Path, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    class MemS3:
        async def download_to_file(self, key: str, target: Path, limit: int) -> int:
            target.write_bytes(b"fake-docx")
            return 9

        async def put_bytes(self, key: str, data: bytes, media_type: str) -> str:
            return "crc=="

    class MemStub:
        def __init__(self) -> None:
            self.saved = 0

        async def GetBlobArtifacts(
            self, req: internal.BlobRequest
        ) -> internal.GetBlobArtifactsResponse:
            return internal.GetBlobArtifactsResponse(
                outcome=internal.BlobProcessingOutcome(obsolete=False, stage="queued"),
                workspace_id="ws-1",
                blob_id=req.blob_id,
                object_key="k",
                media_type=DOCX_MEDIA,
                source_name="doc.docx",
            )

        async def SaveParsedArtifacts(
            self, req: internal.SaveParsedArtifactsRequest
        ) -> internal.BlobProcessingOutcome:
            self.saved += 1
            return internal.BlobProcessingOutcome(obsolete=False, stage="parsed")

    class OkResult:
        success = True

    calls = 0

    class FlakyDatalab:
        async def convert(
            self,
            *,
            file_url: str | None,
            file_path: Path | None,
            options: object,
            stream_response_to: Path,
        ) -> OkResult:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise DatalabAPIError(
                    "Request failed: [Errno 104] Connection reset by peer",
                    status_code=None,
                )
            stream_response_to.write_text(
                json.dumps(
                    {
                        "success": True,
                        "page_count": 1,
                        "markdown": "# Recovered\n\nRecovered document body.\n",
                        "images": {},
                    }
                )
            )
            return OkResult()

    async def _fast_sleep(_sec: float) -> None:
        return None

    def _noop(*_args: object) -> None:
        return None

    monkeypatch.setattr("letfs_ingest.parse.preflight", _noop)
    monkeypatch.setattr("letfs_ingest.telemetry.activity.heartbeat", _noop)
    monkeypatch.setattr("letfs_ingest.parse.asyncio.sleep", _fast_sleep)

    stub = MemStub()
    await Parser(
        cast(Any, stub),
        cast(S3Store, MemS3()),
        config,
        cast(Any, FlakyDatalab()),
    ).run("blob-retry")
    assert calls == 3
    assert stub.saved == 1

    auth_calls = 0

    class AuthFailDatalab:
        async def convert(self, **kwargs: object) -> OkResult:
            nonlocal auth_calls
            auth_calls += 1
            raise DatalabAuthenticationError("bad api key", status_code=401)

    with pytest.raises(ApplicationError, match="bad api key") as exc_info:
        await Parser(
            cast(Any, stub),
            cast(S3Store, MemS3()),
            config,
            cast(Any, AuthFailDatalab()),
        ).run("blob-perm")
    assert auth_calls == 1
    assert exc_info.value.non_retryable is True
    _ = tmp_path
