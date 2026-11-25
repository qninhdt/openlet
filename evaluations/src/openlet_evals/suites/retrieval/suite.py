"""Retrieval suite: dataset validation, deterministic Recall/MRR, and DeepEval evaluation."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from deepeval import evaluate  # pyright: ignore[reportUnknownVariableType]
from deepeval.evaluate.configs import AsyncConfig, CacheConfig, DisplayConfig
from deepeval.metrics import ContextualPrecisionMetric, ContextualRecallMetric
from deepeval.test_case import LLMTestCase
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict

from openlet_evals.core.judge import make_judge
from openlet_evals.core.report import build_run, render_markdown, save_run

from .corpus import COLLECTION, EphemeralQdrant, embed_queries, load_shared_corpus
from .search import SearchMode, search_qdrant


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "retrieval-baseline"
    dataset_file: str = "datasets/letfs/retrieval.json"
    datasets_dir: str = "datasets"
    mode: SearchMode = "hybrid"
    top_k: int = 5
    prefetch_limit: int = 50
    embedding_model: str = "text-embedding-3-large"
    embedding_dimensions: int = 1536
    use_judge: bool = True
    judge_model: str = "gpt-6-luna"
    judge_reasoning_effort: str | None = "max"
    judge_threshold: float = 0.7
    concurrency: int = 20
    use_cache: bool = False


def recall_at_k(relevant: Sequence[str], hit_files: Sequence[str], k: int) -> float:
    rel = set(relevant)
    return len(rel & set(hit_files[:k])) / len(rel) if rel else 0.0


def mrr_at_k(relevant: Sequence[str], hit_files: Sequence[str], k: int) -> float:
    rel = set(relevant)
    for rank, path in enumerate(hit_files[:k], start=1):
        if path in rel:
            return 1.0 / rank
    return 0.0


def load_goldens(path: Path) -> list[dict[str, Any]]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected JSON list in {path}")
    return cast(list[dict[str, Any]], raw)


def validate_goldens(
    goldens: Sequence[dict[str, Any]], indexed_by_ws: dict[str, set[str]]
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for i, g in enumerate(goldens):
        if set(g.keys()) != {"input", "expected_output", "additional_metadata"}:
            errors.append(f"sample[{i}]: unexpected keys {sorted(g.keys())}")
            continue
        meta = cast(dict[str, Any], g["additional_metadata"])
        if set(meta.keys()) != {"id", "workspace", "relevant_files"}:
            errors.append(
                f"sample[{i}]: unexpected metadata keys {sorted(meta.keys())}"
            )
            continue
        sid, ws, rels = (
            str(meta["id"]),
            str(meta["workspace"]),
            list(meta["relevant_files"]),
        )
        if sid in seen:
            errors.append(f"duplicate id: {sid}")
        seen.add(sid)
        ws_idx = indexed_by_ws.get(ws)
        if ws_idx is None:
            errors.append(f"{sid}: unknown workspace {ws}")
            continue
        for rf in rels:
            if rf not in ws_idx:
                errors.append(f"{sid}: missing from {ws}/shared index: {rf}")
    return errors


def validate_retrieval(
    repo_root: Path, cfg: RetrievalConfig
) -> tuple[int, dict[str, int], dict[str, int], list[str]]:
    goldens = load_goldens(repo_root / cfg.dataset_file)
    _, _, indexed_by_ws, blobs_by_ws, pts_by_ws = load_shared_corpus(
        repo_root / cfg.datasets_dir
    )
    return (
        len(goldens),
        blobs_by_ws,
        pts_by_ws,
        validate_goldens(goldens, indexed_by_ws),
    )


def run_retrieval(
    repo_root: Path,
    cfg: RetrievalConfig,
    *,
    limit: int | None = None,
    output_path: Path | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    env = {
        **{k: v for k, v in dotenv_values(repo_root / ".env").items() if v is not None},
        **os.environ,
    }
    goldens = load_goldens(repo_root / cfg.dataset_file)
    points, bid_to_path, indexed_by_ws, _, _ = load_shared_corpus(
        repo_root / cfg.datasets_dir
    )
    errors = validate_goldens(goldens, indexed_by_ws)
    if errors:
        raise ValueError("Validation failed:\n" + "\n".join(errors[:20]))
    if limit is not None:
        goldens = goldens[:limit]

    base_url, api_key = env.get("OPENAI_BASE_URL", ""), env.get("OPENAI_API_KEY", "")
    eval_dir = repo_root / ".local" / "evals"

    if cfg.mode == "bm25":
        qvecs = [[0.0] * cfg.embedding_dimensions for _ in goldens]
    else:
        cache_file = (
            eval_dir
            / "cache"
            / f"query_embeddings_{cfg.embedding_model.replace('/', '_')}_{cfg.embedding_dimensions}.json"
        )
        qvecs = embed_queries(
            [str(g["input"]) for g in goldens],
            base_url=base_url,
            api_key=api_key,
            model=cfg.embedding_model,
            dimensions=cfg.embedding_dimensions,
            cache_path=cache_file,
        )

    t0 = time.perf_counter()
    hits_by_sample: list[list[dict[str, object]]] = []
    with EphemeralQdrant(dimensions=cfg.embedding_dimensions) as qdrant:
        for i in range(0, len(points), 256):
            qdrant.upsert(COLLECTION, points[i : i + 256], wait=True)
        for g, vec in zip(goldens, qvecs, strict=True):
            ws = str(g["additional_metadata"]["workspace"])
            hits_by_sample.append(
                search_qdrant(
                    qdrant,
                    bid_to_path,
                    query=str(g["input"]),
                    vector=vec,
                    workspace=ws,
                    mode=cfg.mode,
                    top_k=cfg.top_k,
                    prefetch_limit=cfg.prefetch_limit,
                )
            )

    judge_scores: list[dict[str, float]] = [{} for _ in goldens]
    if cfg.use_judge:
        judge = make_judge(
            model=cfg.judge_model,
            base_url=base_url,
            api_key=api_key,
            reasoning_effort=cfg.judge_reasoning_effort,
        )
        test_cases = [
            LLMTestCase(
                name=str(g["additional_metadata"]["id"]),
                tags=[str(g["additional_metadata"]["workspace"]), cfg.mode],
                input=str(g["input"]),
                actual_output="",
                expected_output=str(g["expected_output"]),
                retrieval_context=[str(h["text"]) for h in hits],
                metadata=cast(dict[str, Any], g["additional_metadata"]),
            )
            for g, hits in zip(goldens, hits_by_sample, strict=True)
        ]
        result = evaluate(
            test_cases=test_cases,
            metrics=[
                ContextualRecallMetric(
                    threshold=cfg.judge_threshold, model=judge, include_reason=False
                ),
                ContextualPrecisionMetric(
                    threshold=cfg.judge_threshold, model=judge, include_reason=False
                ),
            ],
            identifier=cfg.name,
            async_config=AsyncConfig(run_async=True, max_concurrent=cfg.concurrency),
            cache_config=CacheConfig(write_cache=True, use_cache=cfg.use_cache),
            display_config=DisplayConfig(show_indicator=False, print_results=False),
        )
        idx_by_id = {
            str(g["additional_metadata"]["id"]): i for i, g in enumerate(goldens)
        }
        for tr in result.test_results:
            idx = idx_by_id.get(getattr(tr, "name", "") or "")
            if idx is None:
                continue
            for md in tr.metrics_data or []:
                key = md.name.lower().replace(" ", "_")
                judge_scores[idx][key] = round(float(md.score or 0.0), 6)

    samples: list[dict[str, Any]] = []
    for g, hits, jscores in zip(goldens, hits_by_sample, judge_scores, strict=True):
        meta = cast(dict[str, Any], g["additional_metadata"])
        rels: list[str] = list(meta["relevant_files"])
        hit_files = [str(h["file"]) for h in hits]
        scores = {
            **{
                f"recall@{k}": round(recall_at_k(rels, hit_files, k), 6)
                for k in (1, 3, cfg.top_k)
                if k <= cfg.top_k
            },
            f"mrr@{cfg.top_k}": round(mrr_at_k(rels, hit_files, cfg.top_k), 6),
            **jscores,
        }
        samples.append(
            {
                "id": str(meta["id"]),
                "group": str(meta["workspace"]),
                "scores": scores,
                "relevant_files": rels,
                "top_files": hit_files,
            }
        )

    run = build_run(
        suite="retrieval",
        name=cfg.name,
        config=cfg.model_dump(),
        samples=samples,
        wall_s=time.perf_counter() - t0,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    json_out = output_path or (eval_dir / "runs" / f"{stamp}_{cfg.name}.json")
    md_out = json_out.with_suffix(".md")
    save_run(run, json_out)
    md_out.write_text(render_markdown(run), encoding="utf-8")
    return run, json_out, md_out
