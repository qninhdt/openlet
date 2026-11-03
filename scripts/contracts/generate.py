"""Generate protobuf bindings once per language, or detect generation drift."""

import argparse
import json
import re
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


def action_bindings() -> dict[Path, str]:
    formatter = shutil.which("gofmt")
    if formatter is None:
        raise SystemExit(
            "Go toolchain is required: add its bin directory to PATH (gofmt missing)"
        )
    # Permission declarations are the authority for both handwritten runtimes.
    schema = (CONTRACTS / "authz/schema.zed").read_text()
    resources = {}
    for name, body in re.findall(r"definition (\w+) \{([^}]+)\}", schema):
        if name in {"account", "workspace", "filesystem", "quota_bucket"}:
            resources[name] = re.findall(r"permission (\w+) =", body)
    # Workspace exposes inherited storage permissions too; checks use the owning resource.
    storage = set(resources["filesystem"] + resources["quota_bucket"])
    resources["workspace"] = [
        name for name in resources["workspace"] if name not in storage
    ]
    actions = {
        action: resource for resource, names in resources.items() for action in names
    }
    go = [
        "// Code generated from contracts/authz/schema.zed; DO NOT EDIT.",
        "package authz",
        "",
        "type Action string",
        "",
        "const (",
    ]
    for action in actions:
        name = "".join(word.title() for word in action.split("_"))
        go.append(f'    {name} Action = "{action}"')
    go.extend(
        [
            ")",
            "",
            "func (a Action) Valid(resource string) bool {",
            "    switch resource {",
        ]
    )
    for resource, names in resources.items():
        go.extend(
            [
                f'    case "{resource}":',
                "        switch a {",
                "        case "
                + ", ".join("".join(w.title() for w in n.split("_")) for n in names)
                + ":",
                "            return true",
                "        }",
            ]
        )
    go.extend(["    }", "    return false", "}", ""])
    go_source = subprocess.run(
        [formatter], input="\n".join(go), text=True, capture_output=True, check=True
    ).stdout
    python = "# Generated from contracts/authz/schema.zed; DO NOT EDIT.\nACTION_RESOURCES = {\n"
    python += (
        "".join(
            f'    "{action}": "{resource}",\n' for action, resource in actions.items()
        )
        + "}\n"
    )
    return {
        ROOT / "packages/go/authz/actions.go": go_source,
        ROOT / "packages/python/src/openlet/_authz_actions.py": python,
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
        for target, source in action_bindings().items():
            if args.check:
                if not target.exists() or target.read_text() != source:
                    raise SystemExit(
                        f"Generated actions differ: {target}; run pnpm contracts:generate"
                    )
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source)
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
