"""CLI entrypoint (`openlet-eval`)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from openlet_env.config import find_repo_root
from openlet_sdk.types import is_str_mapping

from openlet_evals.core.report import diff_runs, load_run, render_markdown
from openlet_evals.suites.agent.suite import (
    AgentEvalConfig,
    grade_artifacts,
    run_agent,
    validate_agent,
)
from openlet_evals.suites.retrieval.suite import (
    RetrievalConfig,
    run_retrieval,
    validate_retrieval,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


def _load_yaml(repo_root: Path, config_path: Path | None) -> dict[str, object]:
    if config_path is None:
        return {}
    path = config_path if config_path.is_file() else (repo_root / config_path)
    loaded: object = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not is_str_mapping(loaded):
        raise ValueError(f"Expected YAML mapping in {path}")
    return dict(loaded)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``openlet-eval`` CLI entrypoint."""
    parser = argparse.ArgumentParser(prog="openlet-eval")
    sub = parser.add_subparsers(dest="suite", required=True)

    p_ret = sub.add_parser("retrieval", help="Offline retrieval evaluation.")
    ret_sub = p_ret.add_subparsers(dest="command", required=True)
    p_rval = ret_sub.add_parser(
        "validate", help="Validate Goldens against `.letfs-cache/`."
    )
    p_rval.add_argument("--config", type=Path, default=None)
    p_rrun = ret_sub.add_parser("run", help="Run retrieval evaluation.")
    p_rrun.add_argument("--config", type=Path, default=None)
    p_rrun.add_argument("--name", type=str, default=None)
    p_rrun.add_argument("--mode", choices=("hybrid", "dense", "bm25"), default=None)
    p_rrun.add_argument("--top-k", type=int, default=None)
    p_rrun.add_argument("--no-judge", action="store_true")
    p_rrun.add_argument("--concurrency", type=int, default=None)
    p_rrun.add_argument("--limit", type=int, default=None)
    p_rrun.add_argument("--output", type=Path, default=None)

    p_ag = sub.add_parser("agent", help="Live Leta agent evaluation.")
    ag_sub = p_ag.add_subparsers(dest="command", required=True)
    p_aval = ag_sub.add_parser("validate", help="Validate agent task dataset.")
    p_aval.add_argument("--config", type=Path, default=None)
    p_arun = ag_sub.add_parser("run", help="Run live agent trials and grade.")
    p_arun.add_argument("--config", type=Path, default=None)
    p_arun.add_argument("--name", type=str, default=None)
    p_arun.add_argument("--limit", type=int, default=None)
    p_arun.add_argument("--keep-stack", action="store_true")
    p_arun.add_argument("--output", type=Path, default=None)
    p_agrade = ag_sub.add_parser("grade", help="Re-grade saved `.artifacts.json`.")
    p_agrade.add_argument("artifacts", type=Path)
    p_agrade.add_argument("--config", type=Path, default=None)
    p_agrade.add_argument("--name", type=str, default=None)
    p_agrade.add_argument("--output", type=Path, default=None)

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

    raw = _load_yaml(repo_root, args.config)
    if args.suite == "retrieval":
        if args.command == "run":
            if args.name is not None:
                raw["name"] = args.name
            if args.mode is not None:
                raw["mode"] = args.mode
            if args.top_k is not None:
                raw["top_k"] = args.top_k
            if args.concurrency is not None:
                raw["concurrency"] = args.concurrency
            if args.no_judge:
                raw["use_judge"] = False
        rcfg = RetrievalConfig.model_validate(raw)
        if args.command == "validate":
            n, blobs, pts, errors = validate_retrieval(repo_root, rcfg)
            print(
                f"Goldens: {n} | Blobs: {sum(blobs.values())} | Points: {sum(pts.values())} | Errors: {len(errors)}"
            )
            for err in errors:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1 if errors else 0
        run, json_out, md_out = run_retrieval(
            repo_root, rcfg, limit=args.limit, output_path=args.output
        )
        sys.stdout.write("\n" + render_markdown(run))
        print(f"Saved: {json_out} | {md_out}")
        return 0

    if args.command in ("run", "grade") and args.name is not None:
        raw["name"] = args.name
    acfg = AgentEvalConfig.model_validate(raw)
    if args.command == "validate":
        n, workspaces, errors = validate_agent(repo_root, acfg)
        print(
            f"Tasks: {n} | Workspaces: {', '.join(workspaces) or '(none)'} | Errors: {len(errors)}"
        )
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1 if errors else 0
    if args.command == "grade":
        run, json_out, md_out = grade_artifacts(
            repo_root, acfg, args.artifacts, output_path=args.output
        )
        sys.stdout.write("\n" + render_markdown(run))
        print(f"Saved: {json_out} | {md_out}")
        return 0
    run, json_out, md_out, art_out = run_agent(
        repo_root,
        acfg,
        limit=args.limit,
        keep_stack=args.keep_stack,
        output_path=args.output,
    )
    sys.stdout.write("\n" + render_markdown(run))
    print(f"Saved: {json_out} | {md_out} | {art_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
