import io
import json
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image
from pydantic import ValidationError

from letfs_ingest.openrouter import AISettings, OpenRouter, vision_data
from letfs_ingest.readme import own_body, render_readme
from letfs_ingest.semantic import (
    Metadata,
    csv_profile,
    enrich_tree,
    sample_text,
)
from letfs_ingest.text_split import estimate_tokens


def meta(title="Overview", kind="text:content"):
    return Metadata(
        title=title, description="One sentence.", type=kind, context="Search evidence."
    )


@pytest.mark.parametrize(
    "text", ["hello", "", "Việt Nam 🧪 " * 500, "abc" * 2000, "a\nb\nc\n" * 1000]
)
def test_sampling_budget_and_order(text):
    sampled = sample_text(text, 128)
    assert estimate_tokens(sampled) <= 128
    if estimate_tokens(text) <= 128:
        assert sampled == text
    else:
        assert "[... omitted ...]" in sampled
        assert sampled.startswith(text[:4])
        assert sampled.endswith(text[-4:])


def test_sample_covers_end_and_spaced_intermediate_evidence():
    text = "".join(f"Section {n:04}: " + "prose " * 20 + "\n" for n in range(100))
    text += "Unique final evidence."
    sampled = sample_text(text, 256)
    assert "Section 0000" in sampled
    assert sampled.endswith("Unique final evidence.")


def test_csv_profile_retains_string_ids_mixed_null_and_tail():
    profile = json.loads(csv_profile("id,value\n00123,1\n00124,\n00125,note\n", 2048))
    assert profile["row_count"] == 3
    assert profile["columns"][0]["types"] == {"string": 3}
    assert profile["columns"][1]["types"] == {"integer": 1, "null": 1, "string": 1}
    assert profile["columns"][1]["null_rate"] == pytest.approx(1 / 3)
    assert ["00125", "note"] in profile["samples"]
    assert (
        estimate_tokens(csv_profile("col," * 1000 + "\n" + "value," * 1000, 128)) <= 128
    )


@pytest.mark.parametrize(
    "kind",
    [
        "report",
        "root:report",
        "folder:part",
        "image:research_paper",
        "document:photo",
        "audio:other",
    ],
)
def test_taxonomy_and_metadata_are_validated(kind):
    with pytest.raises(ValidationError):
        meta(kind=kind)
    with pytest.raises(ValidationError):
        meta(title=" ")
    assert meta(kind="document:report").semantic_type == "document:report"


def test_reasoning_effort_is_validated_and_loaded_from_environment(
    monkeypatch, tmp_path
):
    key = tmp_path / "key"
    key.write_text("test-key")
    monkeypatch.setenv("OPENROUTER_API_KEY_FILE", str(key))
    monkeypatch.setenv("OPENROUTER_GENERATION_MODEL", "openai/gpt-6-luna")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "none")
    assert AISettings.from_env().reasoning_effort == "none"
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "invalid")
    with pytest.raises(ValueError, match="reasoning effort"):
        AISettings.from_env()


async def test_instructor_sends_json_and_actual_vision_evidence():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.path == "/api/v1/chat/completions"
        assert body["response_format"] == {"type": "json_object"}
        assert body["reasoning"] == {"effort": "none"}
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": meta(kind="image:chart").model_dump_json(
                                by_alias=True
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            },
        )

    image = io.BytesIO()
    Image.new("RGB", (20, 10)).save(image, format="PNG")
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ai = OpenRouter(
        AISettings(api_key="fake", generation_model="test", reasoning_effort="none"),
        client,
    )
    result = await ai.describe("chart evidence", image.getvalue())
    await ai.close()
    assert result.semantic_type == "image:chart"
    assert calls[0]["messages"][-1]["content"][1]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )
    assert vision_data(image.getvalue()).startswith("data:image/jpeg;base64,")


def node(id, path, parent="root", mime="text/markdown", kind="file"):
    return {
        "id": id,
        "path": path,
        "parent_id": parent,
        "name": path.rsplit("/", 1)[-1],
        "media_type": mime,
        "kind": kind,
    }


@pytest.mark.parametrize("root_kind", ["directory", "file"])
async def test_bottom_up_metadata_names_links_and_original_bytes(root_kind):
    nodes = [
        node(
            "root",
            "",
            None,
            "application/pdf" if root_kind == "file" else None,
            root_kind,
        ),
        node("overview", "README.md"),
        node("part", "1-untitled", kind="directory", mime=None),
        node("part-readme", "1-untitled/README.md", "part"),
        node("leaf", "1-untitled/1-untitled.md", "part"),
        node("image1", "1-untitled/untitled-1.png", "part", "image/png"),
        node("image2", "1-untitled/untitled-2.png", "part", "image/png"),
    ]
    contents = {
        "overview": b"Preamble",
        "part-readme": b"Introduction",
        "leaf": b"Body ![one](untitled-1.png) ![two](untitled-2.png)",
        "image1": b"first image",
        "image2": b"second image",
    }
    original = dict(contents)
    calls = []

    class AI:
        settings = SimpleNamespace(evidence_tokens=1024, concurrency=2)

        async def describe(self, evidence, image):
            own = json.loads(evidence)
            calls.append(own)
            assert estimate_tokens(evidence) <= 1024
            if image is not None:
                return meta("Same image", "image:diagram")
            if own["filename"].endswith("README.md"):
                assert "One sentence." in evidence
                assert own["children"]
                title = (
                    "Part title" if own["own_content"] == "Introduction" else "Overview"
                )
                return meta(title, "document:report")
            return meta("Overview")

    paths, metadata, rewritten = await enrich_tree(nodes, contents, AI())
    assert calls[-2]["own_content"] == "Introduction"
    assert calls[-1]["own_content"] == "Preamble"
    assert calls[-1]["children"][0]["title"] == "Part title"
    assert paths["root"] == ""
    assert paths["part"] == "1-part-title"
    assert paths["leaf"] == "1-part-title/1-overview.md"
    assert paths["image1"] == "1-part-title/same-image.png"
    assert paths["image2"] == "1-part-title/same-image-2.png"
    assert "![two](same-image-2.png)" in rewritten["leaf"].decode()
    header = json.loads(rewritten["overview"].decode().split("\n---\n")[0][4:])
    assert list(header["children"]) == ["1-part-title"]
    assert set(header["children"]["1-part-title"]) == {"title", "description", "type"}
    assert own_body(rewritten["overview"].decode()) == "Preamble"
    assert "part" not in metadata
    if root_kind == "file":
        assert metadata["root"] == metadata["overview"]
        assert "root" not in rewritten
        assert "root" not in contents
    else:
        assert "root" not in metadata
    assert metadata["part-readme"].title == "Part title"
    assert contents == original


async def test_direct_text_has_metadata_and_no_artifacts():
    class AI:
        settings = SimpleNamespace(evidence_tokens=128, concurrency=1)

        async def describe(self, evidence, image):
            assert "original" in evidence
            return meta(kind="text:notes")

    paths, metadata, rewritten = await enrich_tree(
        [node("root", "", None)], {"root": b"original"}, AI()
    )
    assert paths == {"root": ""}
    assert metadata["root"].semantic_type == "text:notes"
    assert rewritten == {}


def test_readme_generated_header_does_not_accumulate():
    rendered = render_readme(meta(), "own text", [])
    assert own_body(rendered) == "own text"
    assert (
        own_body("---\noriginal yaml\n---\n\nbody") == "---\noriginal yaml\n---\n\nbody"
    )


def test_readme_folder_collision_keeps_children_under_their_renamed_parent():
    from letfs_ingest.readme import final_paths

    nodes = [node("root", "", None, None, "directory")]
    metadata = {}
    for index, title in enumerate(["Same", "Same", "Same-2"], 1):
        directory = f"folder-{index}"
        nodes.extend(
            [
                node(directory, directory, kind="directory", mime=None),
                node(f"readme-{index}", f"{directory}/README.md", directory),
                node(f"leaf-{index}", f"{directory}/untitled.md", directory),
            ]
        )
        metadata[f"readme-{index}"] = meta(title)
        metadata[f"leaf-{index}"] = meta("Leaf")
    paths = final_paths(nodes, metadata)
    assert [paths[f"folder-{i}"] for i in (1, 2, 3)] == ["same", "same-3", "same-2"]
    for index in (1, 2, 3):
        assert paths[f"leaf-{index}"] == paths[f"folder-{index}"] + "/leaf.md"
        assert paths[f"readme-{index}"] == paths[f"folder-{index}"] + "/README.md"
