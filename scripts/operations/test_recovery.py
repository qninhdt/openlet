"""Recovery must fence restored authorization before starting any writer."""

import json
from types import SimpleNamespace

import pytest
from recovery import Recovery


def recovery(tmp_path, *, graph=True):
    operation = object.__new__(Recovery)
    operation.state = tmp_path
    services = {
        name: {}
        for name in (
            "postgres",
            "storage",
            "qdrant",
            "boundary",
            "account",
            "workspace",
            "envoy",
        )
    }
    if graph:
        services["spicedb"] = {}
    operation.configuration = {"services": services}
    operation.verify_owner = lambda: None
    calls = []
    operation.command = lambda *args, **kwargs: calls.append(args)
    return SimpleNamespace(operation=operation, calls=calls)


@pytest.mark.parametrize("status", ["restoring", "failed", None])
def test_incomplete_restore_never_starts_dependencies(tmp_path, status):
    fixture = recovery(tmp_path)
    (tmp_path / "restore.json").write_text(json.dumps({"status": status}))

    with pytest.raises(ValueError, match="incomplete restore"):
        fixture.operation.resume()

    assert fixture.calls == []


def test_dump_restore_does_not_establish_graph_readiness(tmp_path):
    fixture = recovery(tmp_path)
    (tmp_path / "restore.json").write_text(json.dumps({"status": "restored"}))

    with pytest.raises(ValueError, match="verified datastore repair"):
        fixture.operation.resume()

    assert fixture.calls == []


def test_repaired_restore_checks_schema_before_starting_application_writers(tmp_path):
    fixture = recovery(tmp_path)
    (tmp_path / "restore.json").write_text(
        json.dumps({"status": "restored", "authorization": "transaction-ids-repaired"})
    )

    fixture.operation.resume()

    check = ("run", "--rm", "--no-deps", "authz-schema", "--check")
    for writer in ("storage", "qdrant", "boundary", "temporal", "account"):
        assert fixture.calls.index(check) < next(
            index
            for index, call in enumerate(fixture.calls)
            if call[0] == "up" and writer in call
        )


@pytest.mark.parametrize("graph", [False, True])
def test_resume_without_restore_marker_keeps_normal_startup(tmp_path, graph):
    fixture = recovery(tmp_path, graph=graph)

    fixture.operation.resume()

    assert any("temporal" in call for call in fixture.calls)
    checks = [call for call in fixture.calls if "authz-schema" in call]
    assert bool(checks) == graph
    if graph:
        assert checks == [("run", "--rm", "--no-deps", "authz-schema", "--check")]
        assert fixture.calls.index(checks[0]) < next(
            index
            for index, call in enumerate(fixture.calls)
            if call[0] == "up" and "temporal" in call
        )


def test_schema_verification_failure_keeps_application_writers_stopped(tmp_path):
    fixture = recovery(tmp_path)

    def command(*args, **kwargs):
        fixture.calls.append(args)
        if "authz-schema" in args:
            raise RuntimeError("schema mismatch")

    fixture.operation.command = command

    with pytest.raises(RuntimeError, match="schema mismatch"):
        fixture.operation.resume()

    for writer in ("storage", "qdrant", "boundary", "temporal", "account"):
        assert not any(call[0] == "up" and writer in call for call in fixture.calls)


def test_rebuild_fences_writers_then_runs_workspace_owner(tmp_path):
    fixture = recovery(tmp_path)

    fixture.operation.rebuild_authorization()

    assert fixture.calls[0] == ("stop", "--timeout", "150", "envoy")
    assert fixture.calls[1][0] == "stop"
    assert {"account", "workspace", "spicedb"}.issubset(fixture.calls[1])
    policy = fixture.calls.index(("run", "--rm", "--no-deps", "authz-schema"))
    for owner in ("workspace",):
        assert policy < fixture.calls.index(
            ("run", "--rm", "--no-deps", "--build", owner, "--rebuild-authorization")
        )
        assert not any(call[0] == "up" and owner in call for call in fixture.calls)


def test_failed_owner_rebuild_cannot_reopen_application_admission(tmp_path):
    fixture = recovery(tmp_path)

    def command(*args, **kwargs):
        fixture.calls.append(args)
        if "--rebuild-authorization" in args and "workspace" in args:
            raise RuntimeError("owner rebuild incomplete")

    fixture.operation.command = command

    with pytest.raises(RuntimeError, match="owner rebuild incomplete"):
        fixture.operation.resume()

    assert fixture.calls[0] == ("stop", "--timeout", "150", "envoy")
    for owner in ("account", "workspace", "envoy", "temporal"):
        assert not any(call[0] == "up" and owner in call for call in fixture.calls)


@pytest.mark.parametrize("version", [1, 2])
def test_old_provider_snapshots_are_rejected_before_side_effects(tmp_path, version):
    fixture = recovery(tmp_path)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "manifest.json").write_text(json.dumps({"version": version}))
    fixture.operation.args = SimpleNamespace(snapshot=snapshot)

    with pytest.raises(ValueError, match="unsupported/incomplete"):
        fixture.operation.restore()

    assert fixture.calls == []


def test_leta_rebuild_reads_workspace_owner_inventory_before_reopening(tmp_path):
    fixture = recovery(tmp_path)
    fixture.operation.configuration["services"].update(
        {"leta-api": {}, "leta-worker": {}, "redis": {}}
    )
    consumed = []
    inventory = (
        b'{"workspace_id":"00000000-0000-0000-0000-000000000001","status":"active"}\n'
    )

    def command(*args, **kwargs):
        fixture.calls.append(args)
        if args[0] == "build":
            return b"#1 Docker build progress is not JSON\n"
        if "--export-resource-workspaces" in args:
            assert "--build" not in args and "-T" in args
            return inventory
        if "leta.rebuild" in args:
            assert "--build" not in args and "-T" in args
            consumed.append(kwargs["stdin"].read())
        return b""

    fixture.operation.command = command
    fixture.operation.resume()
    assert consumed == [inventory]
    export = next(
        i
        for i, call in enumerate(fixture.calls)
        if "--export-resource-workspaces" in call
    )
    rebuild = next(i for i, call in enumerate(fixture.calls) if "leta.rebuild" in call)
    reopen = next(
        i
        for i, call in enumerate(fixture.calls)
        if call[0] == "up" and "leta-worker" in call
    )
    assert export < rebuild < reopen
    assert {"leta-api", "leta-worker", "redis"}.issubset(fixture.calls[1])


def test_leta_rebuild_failure_keeps_workers_and_public_admission_stopped(tmp_path):
    fixture = recovery(tmp_path)
    fixture.operation.configuration["services"]["leta-api"] = {}

    def command(*args, **kwargs):
        fixture.calls.append(args)
        if "leta.rebuild" in args:
            raise RuntimeError("incomplete owner inventory")
        return b""

    fixture.operation.command = command
    with pytest.raises(RuntimeError, match="incomplete owner inventory"):
        fixture.operation.resume()
    assert not any(
        call[0] == "up"
        and ("envoy" in call or "temporal" in call or "leta-api" in call)
        for call in fixture.calls
    )
