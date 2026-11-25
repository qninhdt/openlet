"""Agent evaluation suite: validation, DeepEval Expectations grading, and reporting."""

from __future__ import annotations

import json
import math
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from deepeval import evaluate  # pyright: ignore[reportUnknownVariableType]
from deepeval.dataset import Expectations, Golden
from deepeval.evaluate.configs import (
    AsyncConfig,
    CacheConfig,
    DisplayConfig,
    ErrorConfig,
)
from deepeval.test_case import LLMTestCase
from openlet_env.config import read_user_env
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from openlet_evals.core.judge import make_judge
from openlet_evals.core.report import build_run, render_markdown, save_run

from .runner import DEFAULT_PROMPT_TEMPLATE, TrialArtifact, run_trials

DEFAULT_TOOLS: dict[str, bool] = {
    "hitl": False,
    "multi_agent": False,
    "schedule": False,
    "web": False,
    "execute": True,
    "semantic_search": True,
    "activity": True,
}


ToneKind = Literal["informal", "semi-formal", "formal"]


class TaskMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1)
    tone: ToneKind = "semi-formal"
    skills: list[str] = Field(min_length=1)
    reference_files: list[str] = Field(min_length=1)


class AgentTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    workspace: str = Field(min_length=1)
    task: str = Field(min_length=1)
    must: list[str] = Field(min_length=1)
    must_not: list[str] = Field(default_factory=list)
    tone: ToneKind = "semi-formal"
    skills: list[str] = Field(default_factory=list)
    reference_files: list[str] = Field(default_factory=list)


class AgentEvalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "agent-baseline"
    dataset_file: str = "datasets/leta/retrieval.json"
    datasets_dir: str = "datasets"
    env_project: str = "eval-agent"
    model: str = "openai/gpt-6-luna"
    reasoning_effort: str | None = "max"
    gateway_timeout_seconds: int = 300
    sample_timeout_seconds: float = 1800.0
    trials: int = Field(default=1, ge=1)
    concurrency: int = Field(default=4, ge=1)
    tools: dict[str, bool] = Field(default_factory=lambda: dict(DEFAULT_TOOLS))
    prompt_template: str = DEFAULT_PROMPT_TEMPLATE
    judge_model: str = "gpt-6-luna"
    judge_reasoning_effort: str | None = "max"
    judge_concurrency: int = Field(default=10, ge=1)
    use_cache: bool = False


class Verdict(BaseModel):
    id: str
    status: str
    reason: str = ""
    evidence: str = ""


class GradedTrial(BaseModel):
    artifact: TrialArtifact
    passed: bool
    rubric_score: float
    judge_reason: str | None = None
    judge_error: str | None = None
    verdicts: list[Verdict] = Field(default_factory=list[Verdict])


_GOLDENS_ADAPTER = TypeAdapter(list[Golden])
_ARTIFACTS_ADAPTER = TypeAdapter(list[TrialArtifact])
_VERDICTS_ADAPTER = TypeAdapter(list[Verdict])


def load_tasks(path: Path) -> list[AgentTask]:
    goldens = _GOLDENS_ADAPTER.validate_json(path.read_text(encoding="utf-8"))
    tasks: list[AgentTask] = []
    for idx, g in enumerate(goldens):
        if not g.name or not g.name.strip():
            raise ValueError(f"sample[{idx}]: Golden.name is required")
        if g.expectations is None or not g.expectations.must:
            raise ValueError(f"{g.name}: Golden.expectations.must is required")
        raw_meta: Any = g.additional_metadata  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
        if raw_meta is None:
            raise ValueError(f"{g.name}: Golden.additional_metadata is required")
        meta = TaskMetadata.model_validate(raw_meta)
        tasks.append(
            AgentTask(
                id=g.name.strip(),
                workspace=meta.workspace,
                task=g.input,
                must=list(g.expectations.must),
                must_not=list(g.expectations.must_not),
                tone=meta.tone,
                skills=meta.skills,
                reference_files=meta.reference_files,
            )
        )
    return tasks


def validate_tasks(
    tasks: Sequence[AgentTask],
    available_workspaces: set[str],
    *,
    workspaces_dir: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for t in tasks:
        if t.id in seen:
            errors.append(f"duplicate id: {t.id}")
        seen.add(t.id)
        if t.workspace not in available_workspaces:
            errors.append(f"{t.id}: unknown workspace {t.workspace}")
            continue
        if any(not c.strip() for c in (*t.must, *t.must_not)):
            errors.append(f"{t.id}: empty criterion in must/must_not")
        if workspaces_dir is not None:
            shared_root = workspaces_dir / t.workspace / "storages" / "shared"
            for rf in t.reference_files:
                if not (shared_root / rf.lstrip("/")).is_file():
                    errors.append(f"{t.id}: missing reference_file {rf}")
    return errors


def validate_agent(
    repo_root: Path, cfg: AgentEvalConfig
) -> tuple[int, list[str], list[str]]:
    tasks = load_tasks(repo_root / cfg.dataset_file)
    ws_root = repo_root / cfg.datasets_dir / "workspaces"
    available: set[str] = (
        {p.name for p in ws_root.iterdir() if p.is_dir()} if ws_root.is_dir() else set()
    )
    return (
        len(tasks),
        sorted({t.workspace for t in tasks}),
        validate_tasks(tasks, available, workspaces_dir=ws_root),
    )


def parse_expectation_verdicts(verbose_logs: str | None) -> list[Verdict]:
    try:
        data: Any = json.loads(verbose_logs or "")
        return (
            _VERDICTS_ADAPTER.validate_python(data["verdicts"])
            if isinstance(data, dict) and "verdicts" in data
            else []
        )
    except ValueError, TypeError:
        return []


def grade_trials(
    artifacts: Sequence[TrialArtifact],
    cfg: AgentEvalConfig,
    *,
    base_url: str,
    api_key: str,
) -> list[GradedTrial]:
    """Grade captured trial artifacts using DeepEval native `Expectations`."""
    if not artifacts:
        return []
    non_empty = [a for a in artifacts if a.attachments]
    by_name: dict[str, Any] = {}
    if non_empty:
        judge = make_judge(
            model=cfg.judge_model,
            base_url=base_url,
            api_key=api_key,
            reasoning_effort=cfg.judge_reasoning_effort,
        )
        cases = [
            LLMTestCase(
                name=f"{a.task_id}#t{a.trial}",
                tags=[a.workspace, cfg.name],
                input=a.task,
                actual_output=a.deliverable,
                token_cost=a.usage.cost_usd,
                input_token_count=a.usage.input_tokens,
                output_token_count=a.usage.output_tokens,
                completion_time=a.latency_s,
                expectations=Expectations(
                    must=a.must,
                    must_not=a.must_not,
                    model=judge,
                ),
            )
            for a in non_empty
        ]
        result = evaluate(
            test_cases=cases,
            identifier=cfg.name,
            async_config=AsyncConfig(
                run_async=True, max_concurrent=cfg.judge_concurrency
            ),
            cache_config=CacheConfig(write_cache=True, use_cache=cfg.use_cache),
            error_config=ErrorConfig(ignore_errors=True),
            display_config=DisplayConfig(show_indicator=False, print_results=False),
        )
        by_name = {
            tr.name: tr for tr in result.test_results if getattr(tr, "name", None)
        }

    graded: list[GradedTrial] = []
    for art in artifacts:
        if not art.attachments:
            graded.append(
                GradedTrial(
                    artifact=art,
                    passed=False,
                    rubric_score=0.0,
                    judge_reason="No deliverable files were attached to the final message.",
                )
            )
            continue
        key = f"{art.task_id}#t{art.trial}"
        tr = by_name.get(key)
        md = (tr.metrics_data or [None])[0] if tr is not None else None
        verdicts = parse_expectation_verdicts(md.verbose_logs if md else None)
        passed = bool(md and md.success and (md.score or 0.0) >= 0.999999)
        rubric = (
            round(sum(v.status == "pass" for v in verdicts) / len(verdicts), 6)
            if verdicts
            else (1.0 if passed else 0.0)
        )
        graded.append(
            GradedTrial(
                artifact=art,
                passed=passed,
                rubric_score=rubric,
                judge_reason=md.reason if md else None,
                judge_error=md.error
                if md
                else (None if tr is not None else f"Missing DeepEval result for {key}"),
                verdicts=verdicts,
            )
        )
    return graded


def aggregate_results(
    cfg: AgentEvalConfig, graded: Sequence[GradedTrial], *, wall_s: float
) -> dict[str, Any]:
    """Aggregate pass_at_1/pass_at_k/pass_pow_k, mean_rubric_score, and telemetry."""
    by_task: dict[str, list[GradedTrial]] = defaultdict(list)
    for row in graded:
        by_task[row.artifact.task_id].append(row)

    samples: list[dict[str, Any]] = []
    for tid, rows in by_task.items():
        n = max(1, len(rows))
        passes = sum(r.passed for r in rows)
        scores = {
            "pass_at_1": round(passes / n, 6),
            "mean_rubric_score": round(sum(r.rubric_score for r in rows) / n, 6),
            **(
                {
                    "pass_at_k": float(passes > 0),
                    "pass_pow_k": float(passes == len(rows)),
                }
                if len(rows) > 1 or cfg.trials > 1
                else {}
            ),
        }
        samples.append(
            {
                "id": tid,
                "group": rows[0].artifact.workspace,
                "scores": scores,
                "trials": [
                    {
                        "trial": r.artifact.trial,
                        "status": r.artifact.status,
                        "passed": r.passed,
                        "rubric_score": r.rubric_score,
                        "latency_s": r.artifact.latency_s,
                        "usage": r.artifact.usage.model_dump(),
                        "tool_stats": r.artifact.tool_stats.model_dump(),
                        "judge_reason": r.judge_reason,
                        "judge_error": r.judge_error,
                        "verdicts": [v.model_dump() for v in r.verdicts],
                    }
                    for r in sorted(rows, key=lambda item: item.artifact.trial)
                ],
            }
        )

    n_trials = max(1, len(graded))
    arts = [r.artifact for r in graded]
    in_tok = sum(a.usage.input_tokens for a in arts)
    cached_tok = sum(a.usage.cached_input_tokens for a in arts)
    out_tok = sum(a.usage.output_tokens for a in arts)
    reason_tok = sum(a.usage.reasoning_tokens for a in arts)
    cost = sum(a.usage.cost_usd for a in arts)
    llm_calls = sum(a.usage.llm_calls for a in arts)
    tool_counts: Counter[str] = Counter()
    for a in arts:
        tool_counts.update(a.tool_stats.by_tool)
    total_tools = sum(a.tool_stats.total for a in arts)
    total_errors = sum(a.tool_stats.errors for a in arts)
    lats = sorted(a.latency_s for a in arts)
    p95 = (
        round(lats[max(0, min(len(lats) - 1, math.ceil(0.95 * len(lats)) - 1))], 3)
        if lats
        else 0.0
    )

    telemetry: dict[str, Any] = {
        "completion_rate": round(
            sum(a.status == "completed" for a in arts) / n_trials, 4
        ),
        "avg_input_tokens": round(in_tok / n_trials, 1),
        "avg_cached_input_tokens": round(cached_tok / n_trials, 1),
        "avg_output_tokens": round(out_tok / n_trials, 1),
        "avg_reasoning_tokens": round(reason_tok / n_trials, 1),
        "avg_total_tokens": round((in_tok + out_tok) / n_trials, 1),
        "total_tokens": in_tok + out_tok,
        "avg_cost_usd": round(cost / n_trials, 6),
        "total_cost_usd": round(cost, 6),
        "avg_llm_calls": round(llm_calls / n_trials, 2),
        "avg_tool_calls": round(total_tools / n_trials, 2),
        "tool_errors": total_errors,
        "tool_error_rate": round(total_errors / max(1, total_tools), 4),
        "avg_latency_s": round(sum(lats) / n_trials, 2),
        "p95_latency_s": p95,
        "tool_calls_by_tool": dict(sorted(tool_counts.items())),
    }
    return build_run(
        suite="agent",
        name=cfg.name,
        config=cfg.model_dump(exclude={"prompt_template"}),
        samples=samples,
        wall_s=wall_s,
        telemetry=telemetry,
    )


def _grade_and_save(
    repo_root: Path,
    cfg: AgentEvalConfig,
    artifacts: Sequence[TrialArtifact],
    *,
    started_at: float,
    json_out: Path,
) -> tuple[dict[str, Any], Path, Path]:
    env = read_user_env(repo_root)
    graded = grade_trials(
        artifacts,
        cfg,
        base_url=env.get("OPENAI_BASE_URL", ""),
        api_key=env.get("OPENAI_API_KEY", ""),
    )
    run = aggregate_results(cfg, graded, wall_s=time.perf_counter() - started_at)
    md_out = json_out.with_suffix(".md")
    save_run(run, json_out)
    md_out.write_text(render_markdown(run), encoding="utf-8")
    return run, json_out, md_out


def run_agent(
    repo_root: Path,
    cfg: AgentEvalConfig,
    *,
    limit: int | None = None,
    keep_stack: bool = False,
    output_path: Path | None = None,
) -> tuple[dict[str, Any], Path, Path, Path]:
    tasks = load_tasks(repo_root / cfg.dataset_file)
    _, _, errors = validate_agent(repo_root, cfg)
    if errors:
        raise ValueError("Validation failed:\n" + "\n".join(errors[:20]))
    if limit is not None:
        tasks = tasks[:limit]

    t0 = time.perf_counter()
    artifacts = run_trials(repo_root, cfg, tasks, keep_stack=keep_stack)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    json_out = output_path or (
        repo_root / ".local/evals/runs" / f"{stamp}_{cfg.name}.json"
    )
    art_out = json_out.with_suffix(".artifacts.json")
    art_out.parent.mkdir(parents=True, exist_ok=True)
    art_out.write_bytes(_ARTIFACTS_ADAPTER.dump_json(artifacts, indent=2) + b"\n")

    run, json_out, md_out = _grade_and_save(
        repo_root, cfg, artifacts, started_at=t0, json_out=json_out
    )
    return run, json_out, md_out, art_out


def grade_artifacts(
    repo_root: Path,
    cfg: AgentEvalConfig,
    artifacts_path: Path,
    *,
    output_path: Path | None = None,
) -> tuple[dict[str, Any], Path, Path]:
    artifacts = _ARTIFACTS_ADAPTER.validate_json(
        artifacts_path.read_text(encoding="utf-8")
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    json_out = output_path or (
        repo_root / ".local/evals/runs" / f"{stamp}_{cfg.name}.json"
    )
    return _grade_and_save(
        repo_root,
        cfg,
        artifacts,
        started_at=time.perf_counter(),
        json_out=json_out,
    )
