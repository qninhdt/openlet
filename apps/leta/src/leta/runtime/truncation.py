from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from ..config import ToolOutputConfig


@dataclass(frozen=True, slots=True)
class TruncationResult:
    text: str
    truncated: bool
    start_line: int
    end_line: int
    total_lines: int


def clip_line(line: str, max_chars: int) -> str:
    if max_chars <= 0 or len(line) <= max_chars:
        return line
    return line[:max_chars] + f"... (line truncated to {max_chars} chars)"


def truncate_head(
    text: str,
    *,
    max_lines: int = 2000,
    max_bytes: int = 51200,
    max_line_length: int = 2000,
) -> TruncationResult:
    if not text:
        return TruncationResult("", False, 0, 0, 0)
    raw_lines = text.splitlines()
    total_lines = len(raw_lines)
    kept: list[str] = []
    used_bytes = 0
    truncated = False

    for line in raw_lines:
        if len(kept) >= max_lines:
            truncated = True
            break
        clipped = clip_line(line, max_line_length)
        encoded = (clipped + "\n").encode("utf-8")
        if used_bytes + len(encoded) > max_bytes:
            if not kept:
                # Always keep at least a UTF-8 safe prefix of line 1.
                budget = max(1, max_bytes)
                prefix = clipped.encode("utf-8")[:budget].decode("utf-8", "ignore")
                kept.append(prefix)
            truncated = True
            break
        kept.append(clipped)
        used_bytes += len(encoded)

    if len(kept) < total_lines:
        truncated = True
    return TruncationResult(
        text="\n".join(kept),
        truncated=truncated,
        start_line=1 if kept else 0,
        end_line=len(kept),
        total_lines=total_lines,
    )


def truncate_tail(
    text: str,
    *,
    max_lines: int = 2000,
    max_bytes: int = 51200,
    max_line_length: int = 2000,
) -> TruncationResult:
    """Keep trailing lines up to max_lines / max_bytes with per-line clipping."""
    if not text:
        return TruncationResult("", False, 0, 0, 0)
    raw_lines = text.splitlines()
    total_lines = len(raw_lines)
    kept_rev: list[str] = []
    used_bytes = 0
    truncated = False

    for line in reversed(raw_lines):
        if len(kept_rev) >= max_lines:
            truncated = True
            break
        clipped = clip_line(line, max_line_length)
        if clipped != line:
            truncated = True
        encoded = (clipped + "\n").encode("utf-8")
        if used_bytes + len(encoded) > max_bytes:
            if not kept_rev:
                raw = clipped.encode("utf-8")
                suffix = raw[-max_bytes:].decode("utf-8", "ignore")
                kept_rev.append(suffix)
            truncated = True
            break
        kept_rev.append(clipped)
        used_bytes += len(encoded)

    kept_rev.reverse()
    if len(kept_rev) < total_lines:
        truncated = True
    start_line = total_lines - len(kept_rev) + 1 if kept_rev else 0
    return TruncationResult(
        text="\n".join(kept_rev),
        truncated=truncated,
        start_line=start_line,
        end_line=total_lines,
        total_lines=total_lines,
    )


def spill_filename(prefix: str, cfg: ToolOutputConfig) -> str:
    base = cfg.spill_dir.rstrip("/")
    clean = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in prefix)
    return f"{base}/{clean}-{uuid4().hex[:10]}.txt"


def format_head_truncated(res: TruncationResult, spill_path: str | None) -> str:
    if not res.truncated:
        return res.text
    if spill_path:
        notice = (
            f"\n[showing lines {res.start_line}-{res.end_line} of {res.total_lines}; "
            f"full output saved to {spill_path} — use file_read(path={spill_path!r}, offset=..., limit=...) to inspect more]"
        )
    else:
        notice = (
            f"\n[showing lines {res.start_line}-{res.end_line} of {res.total_lines}; "
            f"output truncated]"
        )
    return res.text + notice


def format_tail_truncated(res: TruncationResult, spill_path: str | None) -> str:
    if not res.truncated:
        return res.text
    if spill_path:
        notice = (
            f"\n[showing lines {res.start_line}-{res.end_line} of {res.total_lines}; "
            f"full output saved to {spill_path} — use file_read(path={spill_path!r}, offset=..., limit=...) to inspect more]"
        )
    else:
        notice = (
            f"\n[showing lines {res.start_line}-{res.end_line} of {res.total_lines}; "
            f"output truncated]"
        )
    return res.text + notice
