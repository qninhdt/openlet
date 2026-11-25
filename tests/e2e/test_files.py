"""Text editing, quota enforcement, copy, ZIP archive download, trash, and restore."""

from __future__ import annotations

import io
import zipfile

from .conftest import AccountFixture, new_uuid


def test_text_editing_quota_copy_trash_restore_and_zip(account: AccountFixture) -> None:
    api = account.api
    base = f"/v1/workspaces/{account.workspace_id}/storages/{account.storage_id}"

    for _ in range(2):
        resp = api.patch(base, json={"name": "Renamed storage"})
        assert resp.is_success, resp.text
        assert resp.json()["name"] == "Renamed storage"

    dirs_payload = {"base": {"nodeId": account.root_id}, "path": "docs/drafts"}
    first = api.post(f"{base}/nodes:createDirectories", json=dirs_payload)
    assert first.is_success, first.text
    again = api.post(f"{base}/nodes:createDirectories", json=dirs_payload)
    assert again.is_success, again.text
    assert again.json()["id"] == first.json()["id"]

    content = "Xin chào\r\nSecond line\n"
    created = api.post(
        f"{base}/nodes",
        json={
            "parent": {"nodeId": account.root_id},
            "name": "notes.txt",
            "text": {"content": content, "mediaType": "text/plain"},
            "requestId": new_uuid(),
        },
    )
    assert created.is_success, created.text
    node = created.json()
    assert node["file"]["type"] == "FILE_TYPE_TEXT"
    assert node["file"]["version"] == "1"
    assert node["file"]["sizeBytes"] == str(len(content.encode("utf-8")))
    assert "processing" not in node["file"]

    edit = {"append": "One append.\n", "expectedVersion": "1", "requestId": new_uuid()}
    appended = api.patch(f"{base}/nodes/{node['id']}/text", json=edit)
    assert appended.is_success, appended.text
    duplicate = api.patch(f"{base}/nodes/{node['id']}/text", json=edit)
    assert duplicate.is_success, duplicate.text
    assert duplicate.json() == appended.json()

    expected_text = content + edit["append"]
    text_resp = api.get(f"{base}/nodes/{node['id']}/text?include_metrics=true")
    assert text_resp.is_success, text_resp.text
    assert text_resp.json()["content"] == expected_text

    quota_url = f"/v1/workspaces/{account.workspace_id}/storage-quota"
    usage = api.get(quota_url).json()["usedBytes"]
    assert usage == str(len(expected_text.encode("utf-8")))
    assert api.patch(quota_url, json={"quotaBytes": "1"}).status_code == 400
    assert api.patch(quota_url, json={"quotaBytes": usage}).is_success

    exhausted = api.patch(
        f"{base}/nodes/{node['id']}/text",
        json={"append": "excess", "requestId": new_uuid()},
    )
    assert exhausted.status_code == 429, exhausted.text
    assert api.patch(quota_url, json={"quotaBytes": "10000"}).is_success

    copied_resp = api.post(
        f"{base}/nodes:copy",
        json={
            "source": {"nodeId": node["id"]},
            "destinationStorageId": account.storage_id,
            "parent": {"nodeId": account.root_id},
            "name": "copy.txt",
            "requestId": new_uuid(),
        },
    )
    assert copied_resp.is_success, copied_resp.text
    copied = copied_resp.json()

    archived = api.post(
        f"{base}/nodes:downloadArchive",
        json={"targets": [{"nodeId": copied["id"]}, {"nodeId": node["id"]}]},
    )
    assert archived.is_success, archived.text
    assert "application/zip" in archived.headers["content-type"]
    with zipfile.ZipFile(io.BytesIO(archived.content)) as zf:
        assert zf.read("copy.txt").decode("utf-8") == expected_text
        assert zf.read("notes.txt").decode("utf-8") == expected_text

    trashed = api.post(
        f"{base}/nodes/{copied['id']}:trash", json={"requestId": new_uuid()}
    )
    assert trashed.is_success, trashed.text
    entry = trashed.json()
    assert api.get(f"{base}/nodes/{copied['id']}").status_code == 404

    restored = api.post(f"{base}/trash/{entry['id']}:restore", json={})
    assert restored.is_success, restored.text
    assert api.get(f"{base}/nodes/{copied['id']}/text").is_success
