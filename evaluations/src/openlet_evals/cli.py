"""CLI entrypoint (`openlet-eval`)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import yaml
from openlet_env.config import find_repo_root

from .core.report import diff_runs, load_run, render_markdown
from .suites.retrieval.suite import RetrievalConfig, run_retrieval, validate_retrieval


def _load_config(repo_root: Path, args: argparse.Namespace) -> RetrievalConfig:
    raw: dict[str, Any] = {}
    if args.config is not None:
        path = args.config if args.config.is_absolute() else (repo_root / args.config)
        loaded: object = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"Expected YAML mapping in {path}")
        raw = {str(k): v for k, v in cast(dict[object, object], loaded).items()}

    for attr, key in (
        ("name", "name"),
        ("mode", "mode"),
        ("top_k", "top_k"),
        ("concurrency", "concurrency"),
    ):
        val = getattr(args, attr, None)
        if val is not None:
            raw[key] = val
    if getattr(args, "no_judge", False):
        raw["use_judge"] = False
    return RetrievalConfig.model_validate(raw)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openlet-eval")
    sub = parser.add_subparsers(dest="suite", required=True)

    p_ret = sub.add_parser("retrieval", help="Offline retrieval evaluation.")
    ret_sub = p_ret.add_subparsers(dest="command", required=True)

    p_val = ret_sub.add_parser(
        "validate", help="Validate Goldens against `.letfs-cache/`."
    )
    p_val.add_argument("--config", type=Path, default=None)

    p_run = ret_sub.add_parser("run", help="Run retrieval evaluation.")
    p_run.add_argument("--config", type=Path, default=None)
    p_run.add_argument("--name", type=str, default=None)
    p_run.add_argument("--mode", choices=("hybrid", "dense", "bm25"), default=None)
    p_run.add_argument("--top-k", type=int, default=None)
    p_run.add_argument("--no-judge", action="store_true")
    p_run.add_argument("--concurrency", type=int, default=None)
    p_run.add_argument("--limit", type=int, default=None)
    p_run.add_argument("--output", type=Path, default=None)

    p_diff = sub.add_parser("diff", help="Diff two saved EvalRun JSON files.")
    p_diff.add_argument("base", type=Path)
    p_diff.add_argument("candidate", type=Path)
    p_diff.add_argument("--metric", type=str, default=None)

    args = parser.parse_args(argv)
    repo_root = find_repo_root()

    if args.suite == "diff":
        sys.stdout.write(
            diff_runs(load_run(args.base), load_run(args.candidate), metric=args.metric)
        )
        return 0

    cfg = _load_config(repo_root, args)
    if args.command == "validate":
        n, blobs, pts, errors = validate_retrieval(repo_root, cfg)
        print(
            f"Goldens: {n} | Blobs: {sum(blobs.values())} | Points: {sum(pts.values())} | Errors: {len(errors)}"
        )
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1 if errors else 0

    run, json_out, md_out = run_retrieval(
        repo_root, cfg, limit=args.limit, output_path=args.output
    )
    sys.stdout.write("\n" + render_markdown(run))
    print(f"Saved: {json_out} | {md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
