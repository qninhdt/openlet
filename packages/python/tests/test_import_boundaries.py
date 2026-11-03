import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def imports(path: Path) -> set[str]:
    modules = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            modules.update(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_processing_and_parser_are_transport_independent():
    source = ROOT / "apps/letfs-ingest/src/letfs_ingest"
    forbidden = ("grpc", "openlet_api", "temporalio")
    violations = {
        str(path.relative_to(ROOT)): sorted(
            module for module in imports(path) if module.startswith(forbidden)
        )
        for directory in (source / "processing", source / "parser")
        for path in directory.rglob("*.py")
    }
    assert not {path: modules for path, modules in violations.items() if modules}


def test_shared_handwritten_package_never_imports_an_app():
    source = ROOT / "packages/python/src/openlet"
    violations = {
        str(path.relative_to(ROOT)): sorted(
            module
            for module in imports(path)
            if module == "letfs_ingest" or module.startswith("letfs_ingest.")
        )
        for path in source.rglob("*.py")
    }
    assert not {path: modules for path, modules in violations.items() if modules}
