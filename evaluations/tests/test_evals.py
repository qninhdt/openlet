"""Unit tests for openlet-evals core and retrieval metrics."""

from __future__ import annotations

from pathlib import Path

import pytest

from openlet_evals.core.judge import make_judge
from openlet_evals.core.report import (
    build_run,
    diff_runs,
    load_run,
    render_markdown,
    save_run,
)
from openlet_evals.suites.retrieval.suite import mrr_at_k, recall_at_k, validate_goldens


def test_make_judge_disables_response_schema_and_sets_reasoning_effort() -> None:
    judge = make_judge(
        model="gpt-6-luna",
        base_url="https://api.vilao.ai/v1",
        api_key="test-key",
        reasoning_effort="max",
    )
    assert judge.supports_structured_outputs() is False
    assert judge.supports_json_mode() is False
    assert judge.generation_kwargs["extra_body"] == {"reasoning_effort": "max"}  # pyright: ignore[reportUnknownMemberType]


def test_recall_and_mrr_deduplicate_hits() -> None:
    hits = ["/a.pdf/01.md", "/a.pdf/01.md", "/b.pdf/README.md", "/c.pdf/README.md"]
    rel = ["/b.pdf/README.md", "/c.pdf/README.md"]
    assert recall_at_k(rel, hits, 1) == 0.0
    assert recall_at_k(rel, hits, 3) == 0.5
    assert recall_at_k(rel, hits, 5) == 1.0
    assert mrr_at_k(rel, hits, 5) == pytest.approx(1.0 / 3.0)


def test_validate_goldens_flags_missing_and_extra_keys() -> None:
    good = {
        "input": "q",
        "expected_output": "a",
        "additional_metadata": {
            "id": "s-1",
            "workspace": "ws",
            "relevant_files": ["/a.pdf/README.md"],
        },
    }
    bad = {
        "input": "q",
        "expected_output": "a",
        "additional_metadata": {
            "id": "s-1",
            "workspace": "ws",
            "relevant_files": ["/missing.pdf/README.md"],
        },
    }
    errs = validate_goldens([good, bad], {"ws": {"/a.pdf/README.md"}})
    assert len(errs) == 2


def test_report_save_load_and_diff(tmp_path: Path) -> None:
    base = build_run(
        suite="retrieval",
        name="base",
        config={},
        samples=[
            {"id": "s-1", "group": "ws", "scores": {"recall@5": 0.5}},
            {"id": "s-2", "group": "ws", "scores": {"recall@5": 1.0}},
        ],
        wall_s=1.2,
    )
    cand = build_run(
        suite="retrieval",
        name="cand",
        config={},
        samples=[
            {"id": "s-1", "group": "ws", "scores": {"recall@5": 1.0}},
            {"id": "s-2", "group": "ws", "scores": {"recall@5": 1.0}},
        ],
        wall_s=1.3,
    )
    out = tmp_path / "base.json"
    save_run(base, out)
    loaded = load_run(out)
    assert loaded["metrics"]["recall@5"] == 0.75
    assert "# Eval: `base` (retrieval)" in render_markdown(loaded)
    diff_md = diff_runs(loaded, cand)
    assert "+0.2500" in diff_md
    assert "`s-1`" in diff_md
    assert "`s-2`" not in diff_md
