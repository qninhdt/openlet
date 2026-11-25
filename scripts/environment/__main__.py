"""Start and seed an Openlet environment."""

import argparse
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

import grpc
import httpx
import psycopg
from openlet_sdk.config import load

from scripts.configure import ROOT

from .api import APIError, Clerk
from .compose import Stack
from .dataset import download_dataset
from .install import seed
from .seed import external_id, read_seeds, slug
from .storage import Services


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("up", "seed", "prepare-cache", "token", "down"):
        sub.add_parser(name).add_argument("--project", required=True)
    sub.choices["up"].add_argument(
        "--config",
        type=Path,
        default=os.environ.get("OPENLET_CONFIG", ROOT / ".local/openlet.yaml"),
    )
    sub.choices["up"].add_argument("--build", action="store_true")
    for name in ("seed", "prepare-cache"):
        sub.choices[name].add_argument("--seeds", type=Path)
        sub.choices[name].add_argument("--workspace", action="append", default=[])
    sub.choices["token"].add_argument("--user", required=True)
    sub.choices["down"].add_argument("--volumes", action="store_true")
    arguments = parser.parse_args()
    try:
        stack = Stack(arguments.project)
        if arguments.command == "up":
            stack.up(arguments.config, build=arguments.build)
            api, endpoint, _ = stack.settings()
            print(
                json.dumps({"api_url": api, "object_store_url": f"http://{endpoint}"})
            )
        elif arguments.command == "down":
            stack.run("down", *(["--volumes"] if arguments.volumes else []))
        else:
            api, endpoint, state = stack.settings()
            config = load()
            with ExitStack() as scope:
                http = scope.enter_context(httpx.Client(timeout=90, trust_env=False))
                clerk = Clerk(
                    http,
                    config["auth"]["clerk"],
                    os.environ.get("OPENLET_SEED_CLERK_TEMPLATE", "openlet"),
                )
                if arguments.command == "token":
                    account = clerk.account(
                        external_id(state["namespace"], slug(arguments.user))
                    )
                    print(clerk.token(clerk.session(account["id"])))
                else:
                    directory = arguments.seeds or download_dataset(ROOT / "datasets")
                    users, workspaces = read_seeds(directory, arguments.workspace)
                    has_leta = "leta" in state["profiles"].split(",")
                    if not has_leta and any(
                        spec.manifest.get("agents") for spec in workspaces
                    ):
                        raise ValueError("seed agents require the leta Compose profile")
                    print(
                        json.dumps(
                            seed(
                                Services(scope, stack, config, has_leta),
                                stack,
                                api,
                                endpoint,
                                clerk,
                                state["namespace"],
                                users,
                                workspaces,
                                prepare=arguments.command == "prepare-cache",
                            ),
                            indent=2,
                        )
                    )
    except (
        APIError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        RuntimeError,
        httpx.RequestError,
        grpc.RpcError,
        psycopg.Error,
        subprocess.CalledProcessError,
    ) as error:
        print(f"environment: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
