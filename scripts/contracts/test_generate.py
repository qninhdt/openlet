"""Authorization actions are keyed by their owning resource."""

import runpy
from pathlib import Path

MODULE = runpy.run_path(str(Path(__file__).with_name("generate.py")))


def test_actions_preserve_repeated_names_and_resource_boundary(tmp_path):
    bindings = MODULE["action_bindings"]()
    source = next(source for path, source in bindings.items() if path.suffix == ".py")
    generated = tmp_path / "actions.py"
    generated.write_text(source)
    values = runpy.run_path(str(generated))
    resources = values["RESOURCE_ACTIONS"]
    assert resources == {
        "account": {"read", "update"},
        "workspace": {"read", "update", "manage_members", "delete"},
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
    assert 'AccountRead Action = "read"' in " ".join(go.split())
    assert 'FilesystemRead Action = "read"' in " ".join(go.split())
