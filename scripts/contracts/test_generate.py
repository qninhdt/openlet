"""Authorization bindings preserve the resource boundary across languages."""

import ast
import runpy
from pathlib import Path

MODULE = runpy.run_path(str(Path(__file__).with_name("generate.py")))


def test_storage_permissions_belong_to_storage_resources():
    bindings = MODULE["action_bindings"]()
    python = next(source for path, source in bindings.items() if path.suffix == ".py")
    resources = ast.literal_eval(ast.parse(python).body[0].value)
    assert resources["node_read"] == "filesystem"
    assert resources["bucket_admin"] == "quota_bucket"
    assert resources["workspace_read"] == "workspace"
    assert resources["account_read"] == "account"
    assert "owner" not in resources
