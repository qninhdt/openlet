import asyncio
import os
import sys
from pathlib import Path

import pytest
from openlet.clients.letfs import (
    Generation,
    IndexInput,
    ParseInput,
    Upload,
    UploadReceipt,
    VectorSpace,
)
from openlet.errors import AppError
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from letfs_ingest.parser.convert_child import ResourceLimit
from letfs_ingest.parser.supervisor import supervise
from letfs_ingest.processing.processor import Processor
from letfs_ingest.temporal.activities import Activities


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
    monkeypatch.setenv("INGEST_SERVICE_TOKEN", "must-not-reach-child")

    async def spawn(*args, **kwargs):
        assert "INGEST_SERVICE_TOKEN" not in kwargs["env"]
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
    class API:
        async def prepare_parse(self, source):
            return None

    processor = Processor(tmp_path)
    await processor.process(API(), None, Generation("file", 1))
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("state", ["completing", "finalized", "aborted"])
async def test_output_retry_reconciles_terminal_transfer_without_resending_bytes(
    tmp_path, state
):
    file = tmp_path / "image.png"
    file.write_bytes(b"image")
    calls = []

    class API:
        async def prepare_parse_output(self, source, output):
            calls.append("PrepareParseOutput")
            return Upload("output", state)

        async def complete_output_upload(self, scope, parts):
            calls.append("CompleteOutputUpload")
            assert scope.upload_id == "output"
            assert not parts
            return UploadReceipt("output", "finalized", 5)

    processor = Processor(tmp_path)
    work = processor.upload(
        API(),
        None,
        Generation("file", 1),
        "parse",
        file,
        "image.png",
        ParseInput("pdf", 5, 10, 100, 1, 100),
    )
    if state == "aborted":
        with pytest.raises(AppError) as captured:
            await work
        assert captured.value.reason == "UPLOAD_NOT_ACTIVE"
        assert not captured.value.retryable
    else:
        assert await work == "output"
    assert calls == ["PrepareParseOutput"] + (
        [] if state == "aborted" else ["CompleteOutputUpload"]
    )


@pytest.mark.parametrize("worker_shutdown", [False, True])
async def test_worker_shutdown_leaves_processing_retryable(
    tmp_path, monkeypatch, worker_shutdown
):
    environment = ActivityEnvironment()
    processor = Processor(tmp_path)
    ready = asyncio.Event()
    failures = []

    async def process(*args):
        ready.set()
        await asyncio.Future()

    class API:
        async def abort_parse(self, source, code):
            failures.append(code)

    activities = Activities(processor, API())

    async def abort(source, code):
        failures.append(code)

    monkeypatch.setattr(processor, "process", process)
    monkeypatch.setattr(activities, "abort", abort)
    task = asyncio.create_task(
        environment.run(
            activities.process_file,
            {"file_id": "019ad06b-7d00-7000-9500-000000000001", "generation": 7},
        )
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
    models = Path(
        os.environ.get("DOCLING_MODELS_PATH")
        or pytest.skip("offline Docling models are unavailable")
    )
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
    with pytest.raises(AppError) as captured:
        await supervise(tmp_path / "source", tmp_path, "pdf", tmp_path, 10, 10000)
    assert captured.value.reason == "PROCESSING_FAILED"
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
    processor = Processor(tmp_path)
    reported = []

    async def fail(*args):
        if terminal:
            raise ResourceLimit("bounded evidence")
        raise RuntimeError("transient provider failure")

    class API:
        async def prepare_index(self, source):
            return IndexInput(
                "filesystem",
                "scope",
                source.file_id,
                source.generation,
                (),
                VectorSpace("model", "files", 2),
                100,
            )

        async def fail_index(self, source, code):
            reported.append(("FailIndex", source, code))

        async def fail_enrichment(self, source, code):
            reported.append(("FailEnrichment", source, code))

    activities = Activities(processor, API())
    monkeypatch.setattr(processor, stage, fail)
    with pytest.raises(ApplicationError):
        await environment.run(
            getattr(activities, stage + "_file"),
            {"file_id": "019ad06b-7d00-7000-9500-000000000001", "generation": 7},
        )
    assert bool(reported) == (attempt == 3 or terminal)
    for method, source, code in reported:
        assert method == ("FailIndex" if stage == "index" else "FailEnrichment")
        assert source.generation == 7
        assert code in {"RESOURCE_LIMIT", "PROCESSING_FAILED", "DEPENDENCY_UNAVAILABLE"}
