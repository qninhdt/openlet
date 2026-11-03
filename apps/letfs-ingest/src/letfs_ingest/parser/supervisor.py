import asyncio
import contextlib
import logging
import os
import re
import signal
import sys

from openlet.errors import AppError

from letfs_ingest.parser.convert_child import MAX_SCRATCH_BYTES, check_outputs

LOG = logging.getLogger(__name__)


async def conversion_diagnostic(stream):
    tail = b""
    while chunk := await stream.read(4096):
        tail = (tail + chunk)[-8192:]
    # Dependency stderr can contain document text; retain only our typed receipt.
    for line in reversed(tail.decode("utf-8", errors="replace").splitlines()):
        if re.fullmatch(
            r"OPENLET_CONVERSION_ERROR exit=[234] exception=\w{1,80} "
            r"cause=\w{1,80} peak_rss_kib=\d{1,20}",
            line,
        ):
            return line
    return "no converter diagnostic"


async def supervise(source, output, kind, models, max_outputs, max_bytes):
    environment = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": str(output.parent),
        "USER": "openlet",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "OMP_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
    }
    for key in ("MIN_LEAF_TOKENS", "SPLIT_TOKENS"):
        if key in os.environ:
            environment[key] = os.environ[key]
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "letfs_ingest.parser.convert_child",
        str(source),
        str(output),
        kind,
        str(models),
        str(max_outputs),
        str(max_bytes),
        env=environment,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    diagnostic = asyncio.create_task(conversion_diagnostic(process.stderr))
    waiter = asyncio.create_task(process.wait())
    try:
        async with asyncio.timeout(660):
            while process.returncode is None:
                try:
                    await asyncio.wait_for(asyncio.shield(waiter), 1)
                except TimeoutError:
                    check_outputs(
                        output, max_outputs, min(max_bytes, MAX_SCRATCH_BYTES)
                    )
            summary = await diagnostic
        if process.returncode != 0:
            LOG.warning(
                "converter exited with status %s: %s", process.returncode, summary
            )
            if process.returncode in (3, -9, -24, -25):
                code = "RESOURCE_LIMIT"
            elif process.returncode == 2:
                code = "DOCUMENT_INVALID"
            else:
                code = "PROCESSING_FAILED"
            raise AppError("document conversion failed", reason=code, retryable=False)
    finally:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(asyncio.shield(waiter), 5)
            except TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
                await waiter
        diagnostic.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await diagnostic
