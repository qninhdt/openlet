"""Compact run summary, JSON/Markdown persistence, and A/B diffing."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from openlet_sdk.types import is_mapping
from pydantic import BaseModel, ConfigDict, Field


class EvalSample(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    group: str
    scores: dict[str, float] = Field(default_factory=dict)


class EvalRun(BaseModel):
    suite: str
    name: str
    created_at: str
    wall_s: float
    sample_count: int
    config: dict[str, object] = Field(default_factory=dict)
    metrics: dict[str, float] = Field(default_factory=dict)
    perfect: dict[str, int] = Field(default_factory=dict)
    by_group: dict[str, dict[str, int | float]] = Field(default_factory=dict)
    samples: list[EvalSample] = Field(default_factory=list[EvalSample])
    telemetry: dict[str, object] | None = None


def build_run(
    *,
    suite: str,
    name: str,
    config: Mapping[str, object],
    samples: Sequence[EvalSample],
    wall_s: float,
    telemetry: Mapping[str, object] | None = None,
) -> EvalRun:
    """Aggregate overall and per-group metrics across evaluation samples."""
    sample_list = list(samples)
    keys = list(dict.fromkeys(k for s in sample_list for k in s.scores))
    metrics = {
        k: round(
            sum(s.scores[k] for s in sample_list if k in s.scores)
            / max(1, len(sample_list)),
            6,
        )
        for k in keys
    }
    perfect = {
        k: sum(1 for s in sample_list if s.scores.get(k, 0.0) >= 0.999999) for k in keys
    }
    grouped: dict[str, list[EvalSample]] = defaultdict(list)
    for s in sample_list:
        grouped[s.group].append(s)

    by_group: dict[str, dict[str, int | float]] = {
        grp: {
            "count": len(rows),
            **{
                k: round(sum(r.scores[k] for r in rows if k in r.scores) / len(rows), 6)
                for k in keys
            },
        }
        for grp, rows in sorted(grouped.items())
    }
    return EvalRun(
        suite=suite,
        name=name,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        wall_s=round(wall_s, 2),
        sample_count=len(sample_list),
        config=dict(config),
        metrics=metrics,
        perfect=perfect,
        by_group=by_group,
        samples=sample_list,
        telemetry=dict(telemetry) if telemetry is not None else None,
    )


def save_run(run: EvalRun, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        run.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8"
    )


def load_run(path: Path) -> EvalRun:
    return EvalRun.model_validate_json(path.read_text(encoding="utf-8"))


def _fmt(value: object) -> str:
    if is_mapping(value):
        return ", ".join(f"{k}={v}" for k, v in value.items()) or "-"
    return f"{value:.4f}" if isinstance(value, float) else str(value)


def render_markdown(run: EvalRun) -> str:
    n = run.sample_count
    metrics = run.metrics
    perfect = run.perfect
    lines = [
        f"# Eval: `{run.name}` ({run.suite})",
        "",
        f"- **Created:** `{run.created_at}` | **Samples:** `{n}` | **Wall:** `{run.wall_s}s`",
        "",
        "| Metric | Score | Perfect |",
        "|---|---:|---:|",
        *[
            f"| `{k}` | `{v:.4f}` | `{perfect.get(k, 0)}/{n}` |"
            for k, v in metrics.items()
        ],
    ]
    if run.telemetry:
        lines.extend(
            [
                "",
                "## Telemetry",
                "",
                "| Metric | Value |",
                "|---|---:|",
                *[f"| `{k}` | `{_fmt(v)}` |" for k, v in run.telemetry.items()],
            ]
        )
    if run.by_group and metrics:
        keys = list(metrics)
        lines.extend(
            [
                "",
                "| Group | n | " + " | ".join(f"`{k}`" for k in keys) + " |",
                "|---|---:|" + "---:|" * len(keys),
                *[
                    f"| `{grp}` | {int(vals['count'])} | "
                    + " | ".join(f"`{float(vals.get(k, 0.0)):.4f}`" for k in keys)
                    + " |"
                    for grp, vals in run.by_group.items()
                ],
            ]
        )
    return "\n".join(lines) + "\n"


def _diff_table(
    base_map: Mapping[str, object], cand_map: Mapping[str, object], keys: list[str]
) -> list[str]:
    rows = ["| Metric | Base | Candidate | Delta |", "|---|---:|---:|---:|"]
    for k in keys:
        bv, cv = base_map.get(k), cand_map.get(k)
        b = float(bv) if isinstance(bv, int | float) else None
        c = float(cv) if isinstance(cv, int | float) else None
        delta = f"{c - b:+.4f}" if (b is not None and c is not None) else "n/a"
        rows.append(
            f"| `{k}` | `{f'{b:.4f}' if b is not None else 'n/a'}` | "
            f"`{f'{c:.4f}' if c is not None else 'n/a'}` | `{delta}` |"
        )
    return rows


def diff_runs(base: EvalRun, cand: EvalRun, *, metric: str | None = None) -> str:
    keys = list(dict.fromkeys([*base.metrics, *cand.metrics]))
    lines = [
        f"# Eval Diff: `{base.name}` → `{cand.name}`",
        "",
        *_diff_table(base.metrics, cand.metrics, keys),
    ]
    b_tel = base.telemetry or {}
    c_tel = cand.telemetry or {}
    tel_keys = [
        k
        for k in dict.fromkeys([*b_tel, *c_tel])
        if isinstance(b_tel.get(k), int | float)
        or isinstance(c_tel.get(k), int | float)
    ]
    if tel_keys:
        lines.extend(
            ["", "## Telemetry Diff", "", *_diff_table(b_tel, c_tel, tel_keys)]
        )

    focus = metric or (
        "pass_at_1"
        if "pass_at_1" in keys
        else "contextual_recall"
        if "contextual_recall" in keys
        else (keys[0] if keys else None)
    )
    if focus:
        b_map = {s.id: s.scores.get(focus) for s in base.samples}
        c_map = {s.id: s.scores.get(focus) for s in cand.samples}
        changed = sorted(
            (
                cv - bv,
                sid,
                bv,
                cv,
            )
            for sid, bv in b_map.items()
            if bv is not None
            and (cv := c_map.get(sid)) is not None
            and abs(cv - bv) > 1e-6
        )
        if changed:
            lines.extend(
                [
                    "",
                    f"## Changed on `{focus}` ({len(changed)} samples)",
                    "",
                    "| Sample | Base | Candidate | Delta |",
                    "|---|---:|---:|---:|",
                    *[
                        f"| `{sid}` | `{bv:.2f}` | `{cv:.2f}` | `{d:+.2f}` |"
                        for d, sid, bv, cv in changed
                    ],
                ]
            )
    return "\n".join(lines) + "\n"
