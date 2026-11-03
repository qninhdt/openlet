"""Generate protobuf bindings once per language, or detect generation drift."""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "packages/contracts"


def run(*args: str, cwd: Path = CONTRACTS) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def generate(destination: Path) -> None:
    template = json.loads((CONTRACTS / "buf.gen.yaml").read_text())
    for plugin in template["plugins"]:
        kind = (
            "openapi" if plugin["local"][-1] == "protoc-gen-connect-openapi" else "go"
        )
        plugin["out"] = str(destination / kind)
    run("pnpm", "exec", "buf", "generate", "--template", json.dumps(template))
    descriptor = destination / "contracts.binpb"
    run(
        "pnpm",
        "exec",
        "buf",
        "build",
        "--as-file-descriptor-set",
        "-o",
        str(descriptor),
    )
    python = destination / "python"
    python.mkdir(parents=True)
    run(
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"--descriptor_set_in={descriptor}",
        f"--python_out={python}",
        f"--grpc_python_out={python}",
        f"--pyi_out={python}",
        *[
            str(p.relative_to(CONTRACTS / "proto"))
            for p in sorted((CONTRACTS / "proto").rglob("*.proto"))
        ],
    )
    for directory in sorted(python.rglob("*")):
        if directory.is_dir():
            (directory / "__init__.py").write_text("")


def contents(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    run("pnpm", "exec", "buf", "lint")
    run("pnpm", "exec", "buf", "format", "--diff", "--exit-code")
    with tempfile.TemporaryDirectory(prefix="openlet-codegen-") as scratch:
        temporary = Path(scratch)
        generate(temporary)
        for language, subtree, target in [
            ("go", "openlet_api", ROOT / "packages/go/gen/openlet_api"),
            ("python", "openlet_api", ROOT / "packages/python/src/openlet_api"),
            ("openapi", "", CONTRACTS / "generated"),
        ]:
            source = temporary / language / subtree
            if args.check:
                if contents(source) != contents(target):
                    raise SystemExit(
                        f"Generated {language} bindings differ; run pnpm contracts:generate"
                    )
            else:
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)


if __name__ == "__main__":
    main()
