"""Authorization actions are keyed by their owning resource."""

import json
import runpy
from pathlib import Path

MODULE = runpy.run_path(str(Path(__file__).with_name("generate.py")))


def test_generated_http_errors_match_problem_transport():
    document = json.loads(
        (MODULE["CONTRACTS"] / "generated/letfs.openapi.json").read_text()
    )
    for path in document["paths"].values():
        for operation in path.values():
            if "responses" in operation:
                assert operation["responses"]["default"]["content"] == {
                    "application/problem+json": {
                        "schema": {"$ref": "#/components/schemas/Problem"}
                    }
                }
    problem = document["components"]["schemas"]["Problem"]
    assert problem["properties"]["code"]["type"] == "string"
    assert problem["properties"]["status"]["type"] == "integer"


def test_actions_preserve_repeated_names_and_resource_boundary(tmp_path):
    bindings = MODULE["action_bindings"]()
    source = next(source for path, source in bindings.items() if path.suffix == ".py")
    generated = tmp_path / "actions.py"
    generated.write_text(source)
    values = runpy.run_path(str(generated))
    resources = values["RESOURCE_ACTIONS"]
    assert resources == {
        "leta": {"read", "manage"},
        "workspace": {"read", "update", "manage_members", "create_leta", "delete"},
        "filesystem": {"read", "delete"},
        "scope": {
            "read_metadata",
            "read_content",
            "write",
            "trash",
            "restore",
            "purge",
            "manage_access",
        },
    }
    assert "read_content" not in resources["filesystem"]
    go = next(source for path, source in bindings.items() if path.suffix == ".go")
    assert 'LetaRead Action = "read"' in " ".join(go.split())
    assert 'FilesystemRead Action = "read"' in " ".join(go.split())
