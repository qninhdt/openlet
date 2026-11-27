"""Thin CLI entrypoint for `openlet-env`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .environment import Environment
from .models import EnvMode


def _parse_profiles(raw: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openlet-env",
        description="Manage non-production Openlet environments (local dev, E2E, evaluation).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_up = sub.add_parser("up", help="Start or update an isolated Openlet environment.")
    p_up.add_argument("--project", default="dev")
    p_up.add_argument("--mode", choices=("mock", "live"), default="live")
    p_up.add_argument("--profiles", default="leta")
    p_up.add_argument("--gateway-port", type=int, default=None)
    p_up.add_argument("--override", type=Path, default=None)
    p_up.add_argument("--build", action="store_true")
    p_up.add_argument("--seed-workspace", action="append", default=[])
    p_up.add_argument("--dataset", type=Path, default=None)
    p_up.add_argument("--idempotent-seed", action="store_true")

    p_down = sub.add_parser("down", help="Stop and remove containers.")
    p_down.add_argument("--project", default="dev")
    p_down.add_argument("--volumes", action="store_true")
    p_down.add_argument("--remove-state", action="store_true")

    p_seed = sub.add_parser(
        "seed", help="Seed workspace(s) into a running environment."
    )
    p_seed.add_argument("--project", default="dev")
    p_seed.add_argument("--dataset", type=Path, default=None)
    p_seed.add_argument("--workspace", action="append", default=[])
    p_seed.add_argument("--idempotent", action="store_true")

    p_unseed = sub.add_parser("unseed", help="Remove one seeded workspace.")
    p_unseed.add_argument("--project", default="dev")
    p_unseed.add_argument("workspace", help="Workspace UUID or seeded handle")

    p_reset = sub.add_parser(
        "reset", help="Wipe all seeded data and optionally re-seed."
    )
    p_reset.add_argument("--project", default="dev")
    p_reset.add_argument("--dataset", type=Path, default=None)
    p_reset.add_argument("--seed-workspace", action="append", default=[])

    p_prep = sub.add_parser(
        "prepare-cache", help="Generate `.letfs-cache/` for a dataset."
    )
    p_prep.add_argument("--project", default="dev")
    p_prep.add_argument("--dataset", type=Path, required=True)
    p_prep.add_argument("--workspace", action="append", default=[])

    p_tok = sub.add_parser(
        "token", help="Print a fresh RS256 Bearer JWT for a seeded user."
    )
    p_tok.add_argument("--project", default="dev")
    p_tok.add_argument("--user", required=True)
    p_tok.add_argument("--ttl", type=int, default=3600)

    p_status = sub.add_parser(
        "status", help="Show running endpoints and seeded workspaces."
    )
    p_status.add_argument("--project", default="dev")

    p_logs = sub.add_parser("logs", help="Show Docker Compose logs.")
    p_logs.add_argument("--project", default="dev")
    p_logs.add_argument("--tail", type=int, default=100)
    p_logs.add_argument("--follow", "-f", action="store_true")
    p_logs.add_argument("services", nargs="*")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "up":
        mode: EnvMode = "mock" if args.mode == "mock" else "live"
        env = Environment(
            project=args.project,
            mode=mode,
            profiles=_parse_profiles(args.profiles),
            gateway_port=args.gateway_port,
            override_path=args.override,
        )
        env.up(build=args.build)
        if args.seed_workspace or args.dataset is not None:
            env.seed(
                dataset_dir=args.dataset,
                workspaces=args.seed_workspace,
                idempotent=args.idempotent_seed,
            )
        print(json.dumps(env.status(), indent=2))
        return 0

    env = Environment(project=args.project)

    if args.command == "down":
        env.down(volumes=args.volumes, remove_state=args.remove_state)
        return 0

    if args.command == "seed":
        result = env.seed(
            dataset_dir=args.dataset,
            workspaces=args.workspace,
            idempotent=args.idempotent,
        )
        print(json.dumps(asdict(result), indent=2))
        return 0

    if args.command == "unseed":
        env.unseed(args.workspace)
        return 0

    if args.command == "reset":
        env.reset()
        if args.seed_workspace or args.dataset is not None:
            env.seed(dataset_dir=args.dataset, workspaces=args.seed_workspace)
        print(json.dumps(env.status(), indent=2))
        return 0

    if args.command == "prepare-cache":
        report = env.prepare_cache(dataset_dir=args.dataset, workspaces=args.workspace)
        print(json.dumps(report, indent=2))
        return 0

    if args.command == "token":
        print(env.token(args.user, ttl_seconds=args.ttl))
        return 0

    if args.command == "status":
        print(json.dumps(env.status(), indent=2))
        return 0

    if args.command == "logs":
        output = env.logs(*args.services, tail=args.tail, follow=args.follow)
        if output:
            sys.stdout.write(output)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
