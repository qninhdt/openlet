"""Guard SQL extraction and fixture substitution used by the isolated benchmark."""

import runpy
import sys
from pathlib import Path

import pytest

BENCH = runpy.run_path(str(Path(__file__).with_name("sql-benchmark.py")))


def test_bind_does_not_replace_prefix_of_larger_parameter():
    values = [str(i) for i in range(1, 11)]
    assert BENCH["bind"]("SELECT $10,$1,$2,$10", values) == "SELECT 10,1,2,10"
    assert BENCH["lit"]("report's title") == "'report''s title'"
    assert BENCH["lit"](None) == "NULL"


def test_sql_extraction_rejects_ambiguous_source(tmp_path):
    source = tmp_path / "query.go"
    source.write_text("const q = `SELECT id FROM nodes`")
    assert BENCH["raw"](tmp_path, "query.go", "SELECT id") == "SELECT id FROM nodes"
    source.write_text(
        "const q = `SELECT id FROM nodes`; const other = `SELECT id FROM files`"
    )
    with pytest.raises(AssertionError):
        BENCH["raw"](tmp_path, "query.go", "SELECT id")


def test_command_failure_is_not_a_successful_measurement():
    with pytest.raises(RuntimeError, match="failed fixture"):
        BENCH["run"](
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('failed fixture'); sys.exit(2)",
            ]
        )


def test_audit_extracts_complete_statements():
    from functools import partial

    root = Path(__file__).resolve().parents[2]
    read = partial(BENCH["raw"], root)
    queries = {}

    def collect(label, query, *_positional, args=None, **_kwargs):
        if args is not None:
            query = BENCH["bind"](query, args)
        assert "$" not in query and "%s" not in query
        queries[label] = query

    runpy.run_path(str(Path(__file__).with_name("sql-audit-cases.py")))["audit"](
        read,
        collect,
        lambda *_args: None,
        BENCH["scope"],
        BENCH["fs"],
        BENCH["uid"],
        BENCH["lit"],
        BENCH["bind"],
        read(
            "apps/letfs/internal/filesystem/nodes.go",
            "n.id,n.scope_id,n.parent_id,n.name,n.kind,n.revision,n.size_bytes,n.created_at,n.updated_at,",
        ),
    )
    assert len(queries) >= 40
    assert "FROM tree n LEFT JOIN files" in queries["processing-inventory"]
    assert "ORDER BY n.depth,n.path LIMIT 1002" in queries["processing-inventory"]
    assert "SELECT id,node_id,original_parent_id" in queries["trash-page"]
