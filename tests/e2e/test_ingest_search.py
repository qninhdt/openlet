"""Blob upload (single + multipart), Datalab PDF/DOCX parse, XLSX ingest, and search."""

from __future__ import annotations

from typing import TypedDict

import httpx
import pytest
from openlet_env.loader import crc32c_base64 as crc32c_b64

from .conftest import (
    SAMPLE_FILES_DIR,
    AccountFixture,
    ReadTreeResponse,
    new_uuid,
    poll,
)


class _UploadPart(TypedDict):
    partNumber: int
    checksum: str


class _CompletedPart(_UploadPart):
    etag: str


@pytest.mark.parametrize(
    ("extension", "media_type"),
    [
        ("pdf", "application/pdf"),
        (
            "docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ],
)
def test_datalab_publishes_markdown_artifacts(
    account: AccountFixture,
    extension: str,
    media_type: str,
) -> None:
    api = account.api
    base = f"/v1/workspaces/{account.workspace_id}/storages/{account.storage_id}"
    name = f"sample.{extension}"
    data = (SAMPLE_FILES_DIR / name).read_bytes()

    prepared = api.post(
        f"{base}/uploads",
        json={
            "create": {"parent": {"nodeId": account.root_id}, "name": name},
            "sizeBytes": str(len(data)),
            "mediaType": media_type,
            "checksum": crc32c_b64(data),
            "requestId": new_uuid(),
        },
    )
    assert prepared.is_success, prepared.text
    upload = prepared.json()

    put = httpx.put(
        upload["transfer"]["putUrl"],
        headers=upload["transfer"]["headers"],
        content=data,
        timeout=30.0,
    )
    assert put.is_success, put.text

    completed = api.post(f"{base}/uploads/{upload['id']}:complete", json={})
    assert completed.is_success, completed.text
    node = completed.json()

    def is_ready() -> bool:
        current = api.get(f"{base}/nodes/{node['id']}").json()
        proc = current["file"]["processing"]
        assert "errorCode" not in proc, f"processing failed: {proc}"
        return proc.get("stage") == "ready"

    poll(is_ready, timeout=90.0, interval=0.5, desc=f"{extension} ingest ready")

    tree = api.post(
        f"{base}/nodes:readTree",
        json={"root": {"nodeId": node["id"]}, "maxDepth": 8, "maxNodes": 100},
    )
    assert tree.is_success, tree.text
    entries = ReadTreeResponse.model_validate(tree.json()).entries
    readme = next((e for e in entries if e.path == "README.md"), None)
    assert readme is not None, entries

    artifact = api.get(f"{base}/nodes/{readme.node.id}/text")
    assert artifact.is_success, artifact.text
    assert f"Datalab {extension.upper()} extract." in artifact.json()["content"]


def test_xlsx_ingest_search_and_multipart_upload(account: AccountFixture) -> None:
    api = account.api
    base = f"/v1/workspaces/{account.workspace_id}/storages/{account.storage_id}"
    data = (SAMPLE_FILES_DIR / "sample.xlsx").read_bytes()

    preparation = {
        "create": {"parent": {"nodeId": account.root_id}, "name": "sales.xlsx"},
        "sizeBytes": str(len(data)),
        "mediaType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "checksum": crc32c_b64(data),
        "requestId": new_uuid(),
    }
    prepared = api.post(f"{base}/uploads", json=preparation)
    assert prepared.is_success, prepared.text
    upload = prepared.json()

    replay_prepare = api.post(f"{base}/uploads", json=preparation)
    assert replay_prepare.is_success, replay_prepare.text
    assert replay_prepare.json() == upload

    mismatched = api.post(
        f"{base}/uploads", json={**preparation, "sizeBytes": str(len(data) + 1)}
    )
    assert mismatched.status_code == 409

    put = httpx.put(
        upload["transfer"]["putUrl"],
        headers=upload["transfer"]["headers"],
        content=data,
        timeout=30.0,
    )
    assert put.is_success, put.text

    committed = api.post(f"{base}/uploads/{upload['id']}:complete", json={})
    assert committed.is_success, committed.text
    node = committed.json()
    replay_complete = api.post(f"{base}/uploads/{upload['id']}:complete", json={})
    assert replay_complete.is_success, replay_complete.text
    assert replay_complete.json() == node

    def is_ready() -> bool:
        current = api.get(f"{base}/nodes/{node['id']}").json()
        proc = current["file"]["processing"]
        assert "errorCode" not in proc, f"processing failed: {proc}"
        return proc.get("stage") == "ready"

    poll(is_ready, timeout=90.0, interval=0.5, desc="xlsx ingest ready")

    tree = api.post(
        f"{base}/nodes:readTree",
        json={"root": {"nodeId": node["id"]}, "maxDepth": 8, "maxNodes": 100},
    )
    assert tree.is_success, tree.text
    entries = ReadTreeResponse.model_validate(tree.json()).entries
    readme = next((e for e in entries if e.path == "README.md"), None)
    assert readme is not None
    assert readme.node.readonly is True

    table_entry = next((e for e in entries if e.path.endswith(".csv")), None)
    assert table_entry is not None
    sheet_text = api.get(f"{base}/nodes/{table_entry.node.id}/text").json()["content"]
    assert "Europe,120" in sheet_text

    denied_edit = api.patch(
        f"{base}/nodes/{readme.node.id}/text",
        json={"append": "denied", "requestId": new_uuid()},
    )
    assert denied_edit.status_code >= 400

    search = api.post(
        f"{base}/files:semanticSearch",
        json={"root": {"nodeId": account.root_id}, "query": "Europe"},
    )
    assert search.is_success, search.text
    hits = search.json()["hits"]
    assert 0 < len(hits) <= 10
    assert hits[0]["fileId"] == node["id"]
    assert hits[0]["path"] == "/sales.xlsx"
    assert hits[0]["artifactPath"]

    scoped = api.post(
        f"{base}/files:semanticSearch",
        json={"root": {"nodeId": node["id"]}, "query": "Europe"},
    )
    assert scoped.is_success, scoped.text
    assert scoped.json()["hits"][0]["fileId"] == node["id"]

    text_search = api.post(
        f"{base}/files:textSearch",
        json={"root": {"nodeId": node["id"]}, "query": "Europe", "pageSize": 100},
    )
    assert text_search.is_success, text_search.text
    assert any(
        str(hit.get("artifactPath", "")).endswith(".csv")
        for hit in text_search.json()["hits"]
    )

    download = api.get(f"{base}/nodes/{node['id']}:download")
    assert download.is_success, download.text
    original = httpx.get(download.json()["blob"]["url"], timeout=30.0)
    assert original.is_success
    assert original.content == data

    # Multipart 11 MiB upload and download roundtrip.
    payload = b"a" * (11 * 1024 * 1024)
    multipart = api.post(
        f"{base}/uploads",
        json={
            "create": {"parent": {"nodeId": account.root_id}, "name": "payload.bin"},
            "sizeBytes": str(len(payload)),
            "mediaType": "application/octet-stream",
            "checksum": crc32c_b64(payload),
            "requestId": new_uuid(),
        },
    )
    assert multipart.is_success, multipart.text
    transfer = multipart.json()
    assert transfer["transfer"]["multipart"] is True
    part_size = int(transfer["transfer"]["partSizeBytes"])
    chunks = [payload[i : i + part_size] for i in range(0, len(payload), part_size)]
    parts: list[_UploadPart] = [
        {"partNumber": idx + 1, "checksum": crc32c_b64(chunk)}
        for idx, chunk in enumerate(chunks)
    ]
    signing = api.post(
        f"{base}/uploads/{transfer['id']}:signParts", json={"parts": parts}
    )
    assert signing.is_success, signing.text
    completed_parts: list[_CompletedPart] = []
    for part in signing.json()["parts"]:
        part_num = int(part["partNumber"])
        resp = httpx.put(
            part["url"],
            headers=part["headers"],
            content=chunks[part_num - 1],
            timeout=60.0,
        )
        assert resp.is_success, resp.text
        completed_parts.append(
            {
                "partNumber": parts[part_num - 1]["partNumber"],
                "checksum": parts[part_num - 1]["checksum"],
                "etag": resp.headers["etag"],
            }
        )

    published = api.post(
        f"{base}/uploads/{transfer['id']}:complete",
        json={"parts": completed_parts},
    )
    assert published.is_success, published.text
    mp_dl = api.get(f"{base}/nodes/{published.json()['id']}:download")
    downloaded = httpx.get(mp_dl.json()["blob"]["url"], timeout=60.0)
    assert downloaded.is_success
    assert downloaded.content == payload
