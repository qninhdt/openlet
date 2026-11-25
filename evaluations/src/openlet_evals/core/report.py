"""Compact run summary, JSON/Markdown persistence, and A/B diffing."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def build_run(
    *,
    suite: str,
    name: str,
    config: dict[str, Any],
    samples: list[dict[str, Any]],
    wall_s: float,
) -> dict[str, Any]:
    """Aggregate overall and per-group metrics across sample dicts."""
    keys = list(dict.fromkeys(k for s in samples for k in s["scores"]))
    metrics = {
        k: round(
            sum(s["scores"][k] for s in samples if k in s["scores"])
            / max(1, len(samples)),
            6,
        )
        for k in keys
    }
    perfect = {
        k: sum(1 for s in samples if s["scores"].get(k, 0.0) >= 0.999999) for k in keys
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in samples:
        grouped[str(s["group"])].append(s)

    by_group = {
        grp: {
            "count": len(rows),
            **{
                k: round(
                    sum(r["scores"][k] for r in rows if k in r["scores"]) / len(rows), 6
                )
                for k in keys
            },
        }
        for grp, rows in sorted(grouped.items())
    }
    return {
        "suite": suite,
        "name": name,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "wall_s": round(wall_s, 2),
        "sample_count": len(samples),
        "config": config,
        "metrics": metrics,
        "perfect": perfect,
        "by_group": by_group,
        "samples": samples,
    }


def save_run(run: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")


def load_run(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def render_markdown(run: dict[str, Any]) -> str:
    n = int(run["sample_count"])
    metrics: dict[str, float] = run["metrics"]
    perfect: dict[str, int] = run.get("perfect", {})
    lines = [
        f"# Eval: `{run['name']}` ({run['suite']})",
        "",
        f"- **Created:** `{run['created_at']}` | **Samples:** `{n}` | **Wall:** `{run['wall_s']}s`",
        "",
        "| Metric | Score | Perfect |",
        "|---|---:|---:|",
        *[
            f"| `{k}` | `{v:.4f}` | `{perfect.get(k, 0)}/{n}` |"
            for k, v in metrics.items()
        ],
    ]
    by_group: dict[str, dict[str, Any]] = run.get("by_group", {})
    if by_group and metrics:
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
                    for grp, vals in by_group.items()
                ],
            ]
        )
    return "\n".join(lines) + "\n"


def diff_runs(
    base: dict[str, Any], cand: dict[str, Any], *, metric: str | None = None
) -> str:
    keys = list(dict.fromkeys([*base["metrics"], *cand["metrics"]]))
    lines = [
        f"# Eval Diff: `{base['name']}` → `{cand['name']}`",
        "",
        "| Metric | Base | Candidate | Delta |",
        "|---|---:|---:|---:|",
    ]
    for k in keys:
        b, c = base["metrics"].get(k), cand["metrics"].get(k)
        delta = f"{c - b:+.4f}" if (b is not None and c is not None) else "n/a"
        lines.append(
            f"| `{k}` | `{f'{b:.4f}' if b is not None else 'n/a'}` | "
            f"`{f'{c:.4f}' if c is not None else 'n/a'}` | `{delta}` |"
        )

    focus = metric or (
        "contextual_recall"
        if "contextual_recall" in keys
        else (keys[0] if keys else None)
    )
    if focus:
        b_map = {s["id"]: s["scores"].get(focus) for s in base.get("samples", [])}
        c_map = {s["id"]: s["scores"].get(focus) for s in cand.get("samples", [])}
        changed = sorted(
            (
                (
                    float(c_map[sid]) - float(b_map[sid]),
                    sid,
                    float(b_map[sid]),
                    float(c_map[sid]),
                )
                for sid in b_map
                if sid in c_map
                and b_map[sid] is not None
                and c_map[sid] is not None
                and abs(float(c_map[sid]) - float(b_map[sid])) > 1e-6
            )
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
