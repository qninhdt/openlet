import asyncio
import os
import sys
from pathlib import Path

import httpx
import pytest
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from openlet_processor.activity import Processor, supervise
from openlet_processor.convert_child import ResourceLimit


@pytest.mark.parametrize("cancel", [True, False])
async def test_supervisor_reaps_child_on_cancellation_or_output_limit(
    tmp_path,
    monkeypatch,
    cancel,
):
    original = asyncio.create_subprocess_exec
    ready = tmp_path / "ready"
    output = tmp_path / "output"
    output.mkdir()
    processes = []
    monkeypatch.setenv("PROCESSOR_SERVICE_TOKEN", "must-not-reach-child")

    async def spawn(*args, **kwargs):
        assert "PROCESSOR_SERVICE_TOKEN" not in kwargs["env"]
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        assert kwargs["env"]["HOME"] == str(output.parent)
        assert kwargs["env"]["USER"] == "openlet"
        script = (
            "import pathlib,time;"
            f"pathlib.Path({str(ready)!r}).write_text('ready');"
            f"pathlib.Path({str(output / 'large')!r}).write_bytes(b'1234');"
            "time.sleep(60)"
        )
        process = await original(sys.executable, "-c", script, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    work = asyncio.create_task(supervise(ready, output, "docx", tmp_path, 10, 3))
    async with asyncio.timeout(5):
        while not ready.exists():
            await asyncio.sleep(0.01)
    if cancel:
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
    else:
        with pytest.raises(ResourceLimit):
            await work
    assert len(processes) == 1
    assert processes[0].returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(processes[0].pid, 0)


async def test_committed_result_reconciliation_never_runs_converter(tmp_path):
    def handler(request):
        assert request.url.path.endswith("/prepare")
        return httpx.Response(200, json={"state": "succeeded"})

    processor = Processor("http://letfs", "token", tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as api:
        await processor.process(api, None, "http://letfs/operation")
    assert list(tmp_path.iterdir()) == []


async def test_client_errors_are_terminal_and_do_not_leak_response_body(tmp_path):
    def handler(request):
        return httpx.Response(
            409,
            json={
                "error": {"code": "SOURCE_REPLACED", "message": "secret contents"},
            },
        )

    processor = Processor("http://letfs", "token", tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as api:
        with pytest.raises(ApplicationError) as captured:
            await processor.request(api, "http://letfs/operation", {})
    assert captured.value.type == "SOURCE_REPLACED"
    assert captured.value.non_retryable
    assert "secret" not in str(captured.value)


@pytest.mark.parametrize("worker_shutdown", [False, True])
async def test_worker_shutdown_leaves_processing_retryable(
    tmp_path, monkeypatch, worker_shutdown
):
    environment = ActivityEnvironment()
    processor = Processor("http://letfs", "token", tmp_path)
    ready = asyncio.Event()
    failures = []

    async def process(*args):
        ready.set()
        await asyncio.Future()

    async def abort(api, path, code):
        failures.append(code)

    monkeypatch.setattr(processor, "process", process)
    monkeypatch.setattr(processor, "abort", abort)
    task = asyncio.create_task(
        environment.run(processor.process_file, "019ad06b-7d00-7000-9500-000000000001")
    )
    async with asyncio.timeout(5):
        await ready.wait()
        if worker_shutdown:
            environment.worker_shutdown()
        environment.cancel(
            activity.ActivityCancellationDetails(
                cancel_requested=not worker_shutdown,
                worker_shutdown=worker_shutdown,
            )
        )
        with pytest.raises(asyncio.CancelledError):
            await task
    assert failures == ([] if worker_shutdown else ["PROCESSING_CANCELLED"])


@pytest.mark.parser
async def test_real_child_converts_local_file_with_minimal_environment(tmp_path):
    source = Path(__file__).parent / "fixtures/tiny.docx"
    models = Path(os.environ["DOCLING_MODELS_PATH"])
    await supervise(source, tmp_path, "docx", models, 10, 10000)
    assert "## Conclusion\n\nDone." in (tmp_path / "README.md").read_text()


async def test_supervisor_reports_internal_failure_without_logging_document_text(
    tmp_path, monkeypatch, caplog
):
    original = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        script = (
            "import sys;"
            "sys.stderr.write('private document text\\n'*10000);"
            "sys.stderr.write('OPENLET_CONVERSION_ERROR exit=4 exception=RuntimeError "
            "cause=NoneType peak_rss_kib=1234\\n');"
            "sys.exit(4)"
        )
        return await original(sys.executable, "-c", script, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(ApplicationError) as captured:
        await supervise(tmp_path / "source", tmp_path, "pdf", tmp_path, 10, 10000)
    assert captured.value.type == "PROCESSING_FAILED"
    assert "RuntimeError" in caplog.text
    assert "peak_rss_kib=1234" in caplog.text
    assert "private document text" not in caplog.text


@pytest.mark.parametrize("stage", ["enrich", "index"])
@pytest.mark.parametrize("attempt,terminal", [(1, False), (3, False), (1, True)])
async def test_semantic_stage_reports_failure_only_when_retries_end(
    tmp_path, monkeypatch, stage, attempt, terminal
):
    from dataclasses import replace

    environment = ActivityEnvironment()
    environment.info = replace(environment.info, attempt=attempt)
    processor = Processor("http://letfs", "token", tmp_path)
    reported = []

    async def fail(*args):
        if terminal:
            raise ResourceLimit("bounded evidence")
        raise RuntimeError("transient provider failure")

    async def request(api, path, body):
        reported.append((path, body))
        return {}

    monkeypatch.setattr(processor, stage, fail)
    monkeypatch.setattr(processor, "request", request)
    with pytest.raises(ApplicationError):
        await environment.run(
            getattr(processor, stage + "_file"),
            "019ad06b-7d00-7000-9500-000000000001",
        )
    assert bool(reported) == (attempt == 3 or terminal)
    assert all(path.endswith("/fail") for path, _ in reported)
