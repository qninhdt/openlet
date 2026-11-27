"""End-to-end verification of openlet_env seeding, ACLs, cached artifacts, search, and unseed."""

from __future__ import annotations

import httpx
from openlet_env import Environment

from .conftest import DATASET_DIR, json_object, json_object_list, poll


def test_seeded_workspace_acls_artifacts_search_and_unseed(
    openlet_env: Environment,
) -> None:
    seeded = openlet_env.seed(dataset_dir=DATASET_DIR, workspaces=["acme-review"])
    ws = seeded.workspaces["acme-review"]
    wid = ws.workspace_id
    alice = seeded.users["alice-chen"]
    bob = seeded.users["bob-tran"]

    base_headers_alice = {
        "Authorization": f"Bearer {alice.token}",
        "x-openlet-zed-token": seeded.zed_token,
    }
    base_headers_bob = {
        "Authorization": f"Bearer {bob.token}",
        "x-openlet-zed-token": seeded.zed_token,
    }

    try:
        with (
            httpx.Client(
                base_url=openlet_env.endpoints.api_url,
                headers=base_headers_alice,
                timeout=30.0,
            ) as alice_api,
            httpx.Client(
                base_url=openlet_env.endpoints.api_url,
                headers=base_headers_bob,
                timeout=30.0,
            ) as bob_api,
        ):
            # Both owner and member can view workspace and shared storage.
            assert alice_api.get(f"/v1/workspaces/{wid}").is_success
            assert bob_api.get(f"/v1/workspaces/{wid}").is_success

            shared = ws.storages["shared"]
            shared_id = shared.id
            shared_root = shared.root_node_id
            overview_id = shared.nodes["overview.md"]
            pdf_id = shared.nodes["sample.pdf"]
            docx_id = shared.nodes["sample.docx"]
            xlsx_id = shared.nodes["sample.xlsx"]

            # Bob can read shared markdown file.
            overview = bob_api.get(
                f"/v1/workspaces/{wid}/storages/{shared_id}/nodes/{overview_id}/text"
            )
            assert overview.is_success, overview.text
            assert "Revenue reached $4.2M" in overview.json()["content"]

            # ACL isolation: Alice can read her private storage, Bob gets 403.
            alice_personal = ws.storages["personal/alice-chen"]
            alice_storage_id = alice_personal.id
            alice_note_id = alice_personal.nodes["private-notes.txt"]
            assert alice_api.get(
                f"/v1/workspaces/{wid}/storages/{alice_storage_id}/nodes/{alice_note_id}/text"
            ).is_success
            assert (
                bob_api.get(
                    f"/v1/workspaces/{wid}/storages/{alice_storage_id}"
                ).status_code
                == 403
            )

            # Cached PDF/DOCX/XLSX blobs are immediately stage=ready with searchable artifacts.
            for blob_node_id in (pdf_id, docx_id, xlsx_id):
                node_resp = alice_api.get(
                    f"/v1/workspaces/{wid}/storages/{shared_id}/nodes/{blob_node_id}"
                )
                assert node_resp.is_success, node_resp.text
                assert node_resp.json()["file"]["processing"]["stage"] == "ready"

            tree = alice_api.post(
                f"/v1/workspaces/{wid}/storages/{shared_id}/nodes:readTree",
                json={"root": {"nodeId": pdf_id}, "maxDepth": 4, "maxNodes": 50},
            )
            assert tree.is_success, tree.text
            entries = json_object_list(json_object(tree.json())["entries"])
            readme = next((e for e in entries if e.get("path") == "README.md"), None)
            assert readme is not None
            readme_node = json_object(readme["node"])
            artifact_text = alice_api.get(
                f"/v1/workspaces/{wid}/storages/{shared_id}/nodes/{readme_node['id']}/text"
            )
            assert "European expansion" in artifact_text.json()["content"]

            # Semantic search hits the pre-cached Qdrant vector immediately.
            sem = alice_api.post(
                f"/v1/workspaces/{wid}/storages/{shared_id}/files:semanticSearch",
                json={"root": {"nodeId": shared_root}, "query": "European expansion"},
            )
            assert sem.is_success, sem.text
            hits = sem.json()["hits"]
            assert hits, "expected semantic search hit from pre-cached vector"
            assert hits[0]["fileId"] == pdf_id

            # Seeded Leta agent is active and visible to owner and operator.
            atlas_id = ws.agents["atlas"]
            assert alice_api.get(f"/v1/workspaces/{wid}/letas/{atlas_id}").is_success
            assert bob_api.get(f"/v1/workspaces/{wid}/letas/{atlas_id}").is_success
    finally:
        openlet_env.unseed(wid)

    # Verify unseed completely removed workspace access.
    with httpx.Client(
        base_url=openlet_env.endpoints.api_url,
        headers={"Authorization": f"Bearer {alice.token}"},
        timeout=15.0,
    ) as check_api:
        poll(
            lambda: check_api.get(f"/v1/workspaces/{wid}").status_code in (403, 404),
            timeout=15.0,
            desc="unseeded workspace removed",
        )
