import json

import httpx
import pytest

from openlet_processor.indexing import Qdrant, VectorSpace, evidence_points, index_tree
from openlet_processor.openrouter import AISettings, OpenRouter

SPACE = VectorSpace("model", "files", 2)


def node(id, path="", parent=None, mime="text/plain", kind="file"):
    return {
        "id": id,
        "path": path,
        "parent_id": parent,
        "name": path.rsplit("/", 1)[-1],
        "media_type": mime,
        "kind": kind,
        "title": "Title",
        "description": "Description.",
        "context": "Generated search context.",
    }


def test_chunks_cover_full_text_not_only_overview_and_have_minimal_payload():
    nodes = [node("source")]
    contents = {
        "source": (
            "opening " * 100 + "RARE_INTERIOR_EVIDENCE " + "closing " * 100
        ).encode()
    }
    points = list(evidence_points(nodes, contents, "fs", "source", 1, SPACE, 64, 8))
    assert len(points) > 2
    assert "RARE_INTERIOR_EVIDENCE" not in points[0]["payload"]["text"]
    assert any(
        "RARE_INTERIOR_EVIDENCE" in point["payload"]["text"] for point in points[1:]
    )
    assert len({p["id"] for p in points}) == len(points)
    assert points == list(
        evidence_points(nodes, contents, "fs", "source", 1, SPACE, 64, 8)
    )
    assert all(
        set(p["payload"])
        == {
            "filesystem_id",
            "source_id",
            "file_id",
            "generation",
            "embedding_model",
            "vector_dimension",
            "text",
        }
        for p in points
    )
    assert all(p["payload"]["file_id"] == "source" for p in points)
    for space in (
        VectorSpace("new-model", "files", 2),
        VectorSpace("model", "new-files", 2),
        VectorSpace("model", "files", 3),
    ):
        changed = list(
            evidence_points(nodes, contents, "fs", "source", 1, space, 64, 8)
        )
        assert {p["id"] for p in points}.isdisjoint(p["id"] for p in changed)
    assert (
        points[0]["id"]
        != list(evidence_points(nodes, contents, "fs", "source", 2, SPACE, 64, 8))[0][
            "id"
        ]
    )


def test_readme_aliases_ancestors_and_csv_image_overviews():
    nodes = [
        node("source", kind="directory", mime=None),
        node("readme", "README.md", "source", "text/markdown"),
        node("part", "1-part", "source", None, "directory"),
        node("part-readme", "1-part/README.md", "part", "text/markdown"),
        node("table", "1-part/table.csv", "part", "text/csv"),
        node("image", "1-part/chart.png", "part", "image/png"),
    ]
    contents = {
        "readme": b"root prose",
        "part-readme": b"group prose",
        "table": b"SECRET_ROW_VALUE " * 1000,
        "image": b"binary",
    }
    points = list(evidence_points(nodes, contents, "fs", "source", 1, SPACE, 64, 8))
    assert {p["payload"]["file_id"] for p in points} == {
        "readme",
        "part-readme",
        "table",
        "image",
    }
    assert len(points) == 4
    assert "root prose" in points[0]["payload"]["text"]
    assert "group prose" in points[1]["payload"]["text"]
    assert all("SECRET_ROW_VALUE" not in p["payload"]["text"] for p in points)
    assert points[-1]["payload"]["text"].startswith(
        "Title: Description.\nTitle: Description."
    )


def test_short_text_keeps_exact_evidence_in_its_single_file_point():
    points = list(
        evidence_points(
            [node("source")],
            {"source": b"Incident reference EXACT_ID_3917."},
            "fs",
            "source",
            1,
            SPACE,
            64,
            8,
        )
    )
    assert len(points) == 1
    assert "EXACT_ID_3917" in points[0]["payload"]["text"]


async def test_embedding_order_and_openrouter_endpoint():
    def handler(request):
        assert request.url.path == "/api/v1/embeddings"
        body = json.loads(request.content)
        assert body == {
            "input": ["a", "b"],
            "model": "embedding",
            "dimensions": 2,
            "encoding_format": "float",
        }
        return httpx.Response(
            200,
            json={
                "object": "list",
                "model": "embedding",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.0, 1.0]},
                    {"object": "embedding", "index": 0, "embedding": [1.0, 0.0]},
                ],
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    ai = OpenRouter(
        AISettings(api_key="fake", generation_model="generation"),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await ai.embed(["a", "b"], "embedding", 2) == [[1, 0], [0, 1]]
    await ai.close()


async def test_batch_failure_propagates_and_retry_reuses_point_ids():
    batches = []
    fail = True

    class Store:
        async def ensure_collection(self, space):
            assert space.dimension == 2

        async def upsert(self, space, points):
            batches.append([p["id"] for p in points])
            if fail and len(batches) == 2:
                raise RuntimeError("unavailable")

    class AI:
        async def embed(self, texts, model, dimensions):
            return [[1.0, 0.0] for _ in texts]

    args = (
        [node("source")],
        {"source": b"body " * 400},
        AI(),
        Store(),
        VectorSpace("model", "files", 2),
        "fs",
        "source",
        1,
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        await index_tree(*args, batch_size=2, chunk_tokens=64, overlap=8)
    fail = False
    initial = batches[:]
    batches.clear()
    total = await index_tree(*args, batch_size=2, chunk_tokens=64, overlap=8)
    assert total > 4
    assert initial == batches[:2]


async def test_native_bm25_collection_and_confirmation_contract():
    calls = []

    def handler(request):
        calls.append(
            (
                request.method,
                request.url.path,
                json.loads(request.content) if request.content else None,
            )
        )
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(200, json={"result": {"status": "completed"}})

    async with httpx.AsyncClient(
        base_url="http://qdrant", transport=httpx.MockTransport(handler)
    ) as client:
        qdrant = Qdrant(client)
        space = VectorSpace("model", "files", 2)
        await qdrant.ensure_collection(space)
        await qdrant.upsert(
            space,
            [{"id": "id", "vector": {"dense": [1, 0]}, "payload": {"text": "content"}}],
        )
    text_index = [
        body
        for _, path, body in calls
        if path.endswith("/index") and body["field_name"] == "text"
    ][0]
    assert text_index["field_schema"]["scoring"] is True
    assert text_index["field_schema"]["type"] == "text"


@pytest.mark.parametrize(
    "setting,value",
    [
        ("QDRANT_URL", "file:///tmp/index"),
        ("QDRANT_URL", "http://user:secret@qdrant"),
        ("EMBEDDING_BATCH_SIZE", "0"),
        ("CHUNK_TOKENS", "9000"),
        ("CHUNK_OVERLAP_TOKENS", "1024"),
    ],
)
def test_index_configuration_rejects_invalid_bounds(
    tmp_path, monkeypatch, setting, value
):
    from openlet_processor.indexing import IndexSettings

    key = tmp_path / "qdrant-key"
    key.write_text("test-key")
    monkeypatch.setenv("QDRANT_URL", "http://qdrant:6333")
    monkeypatch.setenv("QDRANT_API_KEY_FILE", str(key))
    assert IndexSettings.from_env().chunk_tokens == 1024
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError):
        IndexSettings.from_env()
