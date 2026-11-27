"""Workspace filesystem, search, edit, and sandboxed bash tools."""

from __future__ import annotations

import asyncio
import bisect
import contextlib
import difflib
import errno
import posixpath
import re
import unicodedata
from contextlib import ExitStack
from typing import TYPE_CHECKING

import grpc
from langchain_core.tools import ToolException
from langgraph.prebuilt import ToolRuntime  # noqa: TC002  # Evaluated at runtime by LangGraph ToolNode.get_type_hints.
from pydantic import Field

from leta.filesystem.types import parse_stat_extra
from leta.filesystem.workspace import canonical_path
from leta.observability import build_rag_baggage
from leta.runtime.media import detect_media_type, optimize_image_bytes
from leta.runtime.state import AgentState, RuntimeContext  # noqa: TC001  # Evaluated at runtime by LangGraph ToolNode.get_type_hints.
from leta.runtime.tools.base import ToolArgs, ToolResult, make_tool
from leta.truncation import clip_line

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from openlet_sdk.config import JSON

    from leta.filesystem.types import GlobHit, GrepHit, NodeStatExtra, SemanticHit
    from leta.filesystem.workspace import Session

_KNOWN_MOUNT_ROOTS = frozenset({"shared", "chat", "user", "letfs", "home"})
_LINE_PREFIX_RE = re.compile(r"^(\d+): (.*)$")


def normalize_workspace_path(raw: str) -> str:
    """Resolve virtual path, auto-fixing missing leading '/' for known workspace mounts."""
    stripped = raw.strip()
    if not stripped:
        return "/home"
    if not stripped.startswith(("/", "~")):
        first = stripped.split("/", 1)[0]
        if first in _KNOWN_MOUNT_ROOTS:
            stripped = "/" + stripped
    return canonical_path(stripped)


_UNICODE_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\u00a0": " ",
        "\u202f": " ",
        "\u205f": " ",
        "\u3000": " ",
    }
)


def _normalize_unicode_text(s: str) -> str:
    return unicodedata.normalize("NFC", s).translate(_UNICODE_TRANSLATION)


def _rank_similar_names(target_name: str, siblings: list[str]) -> list[str]:
    low = target_name.lower()
    stem = posixpath.splitext(low)[0]
    scored: list[tuple[int, float, str]] = []
    for name in siblings:
        n_low = name.lower()
        n_stem = posixpath.splitext(n_low)[0]
        if n_low == low:
            scored.append((0, 0.0, name))
        elif stem and n_stem == stem:
            scored.append((1, 0.0, name))
        elif len(low) >= 3 and (low in n_low or n_low in low):
            scored.append((2, float(abs(len(n_low) - len(low))), name))
        else:
            ratio = difflib.SequenceMatcher(None, low, n_low, autojunk=False).ratio()
            if ratio >= 0.6:
                scored.append((3, -ratio, name))
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    return [name for _, _, name in scored[:3]]


# --- OpenCode v2 LF-view + SequenceMatcher line-ending edit engine ---


def _dominant_line_ending(text: str, fallback: str = "\n") -> str:
    crlf_count = text.count("\r\n")
    lf_count = text.count("\n") - crlf_count
    if crlf_count == lf_count:
        return fallback
    return "\r\n" if crlf_count > lf_count else "\n"


def _align_lines(before: list[str], after: list[str]) -> list[int | None]:
    """Map each `after` line to the `before` line it keeps or replaces via difflib."""
    result: list[int | None] = [None] * len(after)
    matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "replace"):
            for k in range(min(i2 - i1, j2 - j1)):
                result[j1 + k] = i1 + k
    return result


def _with_region_endings(region: str, replacement_lf: str, fallback: str) -> str:
    before = re.split(r"\r?\n", region)
    endings = re.findall(r"\r?\n", region)
    after = replacement_lf.split("\n")

    def _line_key(ln: str) -> str:
        return _normalize_unicode_text(ln.rstrip())

    source_idx = _align_lines(
        [_line_key(b) for b in before], [_line_key(a) for a in after]
    )
    out: list[str] = []
    for idx, line in enumerate(after):
        if idx == len(after) - 1:
            out.append(line)
        else:
            src_i = source_idx[idx]
            ending = (
                endings[src_i]
                if src_i is not None and src_i < len(endings)
                else fallback
            )
            out.append(line + ending)
    return "".join(out)


def _find_all_substring_spans(
    haystack: str, needle: str, *, max_spans: int | None = None
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            break
        spans.append((idx, idx + len(needle)))
        start = idx + max(1, len(needle))
        if max_spans is not None and len(spans) > max_spans:
            break
    return spans


def _match_line_trimmed_spans(
    view: str, search: str, *, replace_all: bool
) -> list[tuple[int, int]]:
    c_lines = view.splitlines(keepends=True)
    o_lines = [_normalize_unicode_text(ln.rstrip()) for ln in search.splitlines()]
    if not o_lines or len(o_lines) > len(c_lines):
        return []
    offsets: list[int] = []
    pos = 0
    for ln in c_lines:
        offsets.append(pos)
        pos += len(ln)
    offsets.append(pos)
    spans: list[tuple[int, int]] = []
    for i in range(len(c_lines) - len(o_lines) + 1):
        window = [
            _normalize_unicode_text(c_lines[i + k].rstrip())
            for k in range(len(o_lines))
        ]
        if window == o_lines:
            end_pos = offsets[i + len(o_lines)]
            if not search.endswith("\n") and c_lines[i + len(o_lines) - 1].endswith(
                "\n"
            ):
                end_pos -= 1
            spans.append((offsets[i], end_pos))
            if not replace_all and len(spans) > 10:
                break
    return spans


def _match_edit_spans(
    view: str, search: str, *, replace_all: bool
) -> tuple[list[tuple[int, int]], int]:
    """3-tier deterministic matcher on LF view: exact -> unicode normalized -> trailing-ws lines."""
    limit = None if replace_all else 10
    if search in view:
        return _find_all_substring_spans(view, search, max_spans=limit), 1

    norm_view = _normalize_unicode_text(view)
    norm_search = _normalize_unicode_text(search)
    if norm_search and norm_search in norm_view and len(norm_view) == len(view):
        spans = _find_all_substring_spans(norm_view, norm_search, max_spans=limit)
        if spans:
            return spans, 2

    spans = _match_line_trimmed_spans(view, search, replace_all=replace_all)
    if spans:
        return spans, 3
    return [], 0


def _try_strip_read_line_prefixes(
    view: str, old_lf: str, new_lf: str
) -> tuple[str, str, str | None]:
    """Auto-heal when model copies '12: <line>' prefixes from file_read output."""
    old_lines = old_lf.split("\n")
    trailing_nl = old_lf.endswith("\n")
    check_lines = old_lines[:-1] if trailing_nl else old_lines
    if not check_lines:
        return old_lf, new_lf, None
    parsed: list[tuple[int, str]] = []
    for ln in check_lines:
        m = _LINE_PREFIX_RE.match(ln)
        if m is None:
            return old_lf, new_lf, None
        parsed.append((int(m.group(1)), m.group(2)))
    # Verify line numbers are sequential and match actual file lines.
    first_no = parsed[0][0]
    if first_no < 1:
        return old_lf, new_lf, None
    file_lines = view.split("\n")
    for idx, (lno, text) in enumerate(parsed):
        if lno != first_no + idx:
            return old_lf, new_lf, None
        f_idx = lno - 1
        if f_idx >= len(file_lines):
            return old_lf, new_lf, None
        if _normalize_unicode_text(
            file_lines[f_idx].rstrip()
        ) != _normalize_unicode_text(text.rstrip()):
            return old_lf, new_lf, None

    stripped_old = "\n".join(text for _, text in parsed) + ("\n" if trailing_nl else "")
    new_lines = new_lf.split("\n")
    new_trailing = new_lf.endswith("\n")
    new_check = new_lines[:-1] if new_trailing else new_lines
    new_matches = [_LINE_PREFIX_RE.match(ln) for ln in new_check]
    if new_matches and all(m is not None for m in new_matches):
        stripped_new = "\n".join(m.group(2) for m in new_matches if m is not None) + (
            "\n" if new_trailing else ""
        )
    else:
        stripped_new = new_lf
    return (
        stripped_old,
        stripped_new,
        "Note: stripped line-number prefixes (e.g. '1: ') copied from file_read output; omit them in future file_edit calls.",
    )


def _build_miss_hint(
    view: str,
    old_lf: str,
    new_lf: str,
    *,
    max_lines: int = 12,
    max_line_len: int = 200,
) -> str:
    if len(new_lf.strip()) >= 8 and _normalize_unicode_text(
        new_lf
    ) in _normalize_unicode_text(view):
        return (
            "old_string was not found, but new_string is already present in the file. "
            "The edit may already have been applied."
        )
    c_lines = view.splitlines()
    o_lines = [ln.strip() for ln in old_lf.splitlines() if ln.strip()]
    if not c_lines or not o_lines:
        return "old_string was not found in the file."

    votes: dict[int, float] = {}
    for oi, needle in enumerate(o_lines[:10]):
        n_low = _normalize_unicode_text(needle).lower()
        for ci, hay in enumerate(c_lines):
            h_low = _normalize_unicode_text(hay.strip()).lower()
            if not h_low:
                continue
            if n_low == h_low:
                score = 2.0
            elif n_low in h_low or h_low in n_low:
                score = 1.0
            else:
                ratio = difflib.SequenceMatcher(None, n_low, h_low).ratio()
                score = ratio if ratio >= 0.6 else 0.0
            if score > 0:
                anchor = max(0, ci - oi)
                votes[anchor] = votes.get(anchor, 0.0) + score

    if not votes:
        return "old_string was not found in the file."
    best_start = max(votes.items(), key=lambda kv: kv[1])[0]
    lo = max(0, best_start - 2)
    hi = min(len(c_lines), lo + max_lines)
    snippet = "\n".join(
        f"{idx + 1}: {c_lines[idx][:max_line_len]}" for idx in range(lo, hi)
    )
    return f"old_string was not found in the file. Closest matching lines:\n{snippet}"


def apply_file_edit_detailed(
    content: str,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
    miss_hint_lines: int = 12,
    miss_hint_line_length: int = 200,
) -> tuple[str, int, str, list[int], str | None]:
    """LF-view edit engine preserving CRLF/mixed endings and BOM; returns (updated, count, diff, line_numbers, note)."""
    if not old_string:
        raise ValueError(
            "old_string must not be empty. Use file_write to create or overwrite a file."
        )
    if old_string == new_string:
        raise ValueError(
            "No changes needed: old_string and new_string are identical. Do not retry with identical text."
        )

    has_bom = content.startswith("\ufeff")
    body = content[1:] if has_bom else content
    endings_only = old_string.replace("\r", "") == new_string.replace("\r", "")
    repair_note: str | None = None

    if endings_only:
        spans_raw: list[tuple[int, int]] = []
        start = 0
        while True:
            idx = body.find(old_string, start)
            if idx < 0:
                break
            spans_raw.append((idx, idx + len(old_string)))
            start = idx + max(1, len(old_string))
        if not spans_raw:
            raise ValueError(
                "old_string was not found with those exact line endings in the file."
            )
        if len(spans_raw) > 1 and not replace_all:
            lnums = [body.count("\n", 0, s) + 1 for s, _ in spans_raw[:10]]
            raise ValueError(
                f"old_string matched {len(spans_raw)} locations (lines {', '.join(map(str, lnums))}). "
                "Add more surrounding context to uniquely identify one match, or set replace_all=true."
            )
        parts: list[str] = []
        last = 0
        for s, e in spans_raw:
            parts.append(body[last:s])
            parts.append(new_string)
            last = e
        parts.append(body[last:])
        new_body = "".join(parts)
        matched_lines = [body.count("\n", 0, s) + 1 for s, _ in spans_raw]
    else:
        view = body.replace("\r\n", "\n")
        crlf_lf_positions = [
            m.start() - idx for idx, m in enumerate(re.finditer(r"\r\n", body))
        ]
        file_ending = _dominant_line_ending(body, "\n")
        old_lf = old_string.replace("\r\n", "\n")
        new_lf = new_string.replace("\r\n", "\n")

        spans_lf, _ = _match_edit_spans(view, old_lf, replace_all=replace_all)
        if not spans_lf:
            stripped_old, stripped_new, note = _try_strip_read_line_prefixes(
                view, old_lf, new_lf
            )
            if note is not None:
                spans_lf, _ = _match_edit_spans(
                    view, stripped_old, replace_all=replace_all
                )
                if spans_lf:
                    old_lf = stripped_old
                    new_lf = stripped_new
                    repair_note = note

        if not spans_lf:
            raise ValueError(
                _build_miss_hint(
                    view,
                    old_lf,
                    new_lf,
                    max_lines=miss_hint_lines,
                    max_line_len=miss_hint_line_length,
                )
            )
        if len(spans_lf) > 1 and not replace_all:
            lnums = [view.count("\n", 0, s) + 1 for s, _ in spans_lf[:10]]
            suffix = "+" if len(spans_lf) > 10 else ""
            raise ValueError(
                f"old_string matched {len(spans_lf)}{suffix} locations (lines {', '.join(map(str, lnums))}). "
                "Add more surrounding context to uniquely identify one location, or set replace_all=true."
            )

        # Map LF-view offsets back into raw body offsets.
        raw_spans = [
            (
                s + bisect.bisect_left(crlf_lf_positions, s),
                e + bisect.bisect_left(crlf_lf_positions, e),
            )
            for s, e in spans_lf
        ]
        parts = []
        last = 0
        for s, e in raw_spans:
            region = body[s:e]
            repl = _with_region_endings(
                region, new_lf, _dominant_line_ending(region, file_ending)
            )
            parts.append(body[last:s])
            parts.append(repl)
            last = e
        parts.append(body[last:])
        new_body = "".join(parts)
        matched_lines = [view.count("\n", 0, s) + 1 for s, _ in spans_lf]

    updated = ("\ufeff" + new_body) if has_bom else new_body
    diff = "".join(
        difflib.unified_diff(
            body.splitlines(keepends=True),
            new_body.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
            n=2,
        )
    )
    return updated, len(matched_lines), diff, matched_lines, repair_note


def apply_file_edit(
    content: str,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
    miss_hint_lines: int = 12,
    miss_hint_line_length: int = 200,
) -> tuple[str, int, str]:
    """Pure edit engine returning (updated_content, count, unified_diff) or raising ValueError."""
    updated, count, diff, _, _ = apply_file_edit_detailed(
        content,
        old_string,
        new_string,
        replace_all=replace_all,
        miss_hint_lines=miss_hint_lines,
        miss_hint_line_length=miss_hint_line_length,
    )
    return updated, count, diff


# --- Pydantic Tool Schemas (Self-Contained Descriptions) ---


class FileReadArgs(ToolArgs):
    """Input schema for ``file_read``."""

    path: str = Field(min_length=1)
    offset: int | None = Field(
        default=None,
        description="1-based start line/entry; negative reads from end.",
    )
    limit: int | None = Field(
        default=None,
        ge=0,
        description="Max lines/entries (capped at 2000).",
    )


class FileEditArgs(ToolArgs):
    """Input schema for ``file_edit``."""

    path: str = Field(min_length=1)
    old_string: str = Field(min_length=1, description="Exact text to replace.")
    new_string: str = Field(description="Replacement text (empty string deletes).")
    replace_all: bool = Field(
        default=False,
        description="Replace all occurrences instead of requiring a unique match.",
    )


class FileWriteArgs(ToolArgs):
    """Input schema for ``file_write``."""

    path: str = Field(min_length=1)
    content: str


class GlobArgs(ToolArgs):
    """Input schema for ``glob``."""

    pattern: str = Field(min_length=1)
    path: str = Field(
        default="/shared",
        description="Search root ('/chat' or '/' searches across mounts).",
    )
    hidden: bool = False
    limit: int = Field(
        default=100,
        ge=1,
        description="Max results (capped at 100).",
    )


class GrepArgs(ToolArgs):
    """Input schema for ``grep``."""

    pattern: str = Field(min_length=1)
    path: str = Field(
        default="/shared",
        description="File or dir ('/chat' or '/' searches across mounts).",
    )
    include: str = Field(
        default="",
        description="Filename glob filter (e.g. '*.csv').",
    )
    literal: bool = False
    case_sensitive: bool = True
    limit: int = Field(
        default=100,
        ge=1,
        description="Max matching lines (capped at 100).",
    )


class SemanticSearchArgs(ToolArgs):
    """Input schema for ``semantic_search``."""

    query: str = Field(min_length=1)
    paths: list[str] = Field(
        default_factory=lambda: ["/shared", "/home"],
        max_length=5,
        description="Up to 5 mounts/paths ('/chat' expands to all mounted chat folders).",
    )
    limit: int = Field(
        default=10,
        ge=1,
        description="Max chunks (capped at 25).",
    )


class BashArgs(ToolArgs):
    """Input schema for ``bash``."""

    command: str = Field(min_length=1)
    workdir: str | None = Field(
        default=None,
        description="Working directory (default '/home'; prefer over 'cd').",
    )
    timeout: int | None = Field(
        default=None,
        ge=1,
        le=600,
        description="Timeout in seconds (not ms; default 120).",
    )


# --- Shared Recovery & Mount Fan-Out Helpers ---


async def missing_path_recovery(
    rt: RuntimeContext,
    abs_path: str,
    *,
    allow_alternate: bool = True,
) -> tuple[str | None, str]:
    """3-layer OpenCode v2 recovery + mount reroot suggestions: (alternate_path, helpful_error)."""
    session = await rt.fs.open()
    parent = posixpath.dirname(abs_path)
    target_name = posixpath.basename(abs_path)

    # Reroot check: if model passed a relative path that resolved under /home/..., check /shared & /chat/*.
    reroot_suggestions: list[str] = []
    if abs_path.startswith("/home/") and len(abs_path) > 6:
        rel = abs_path.removeprefix("/home/")
        candidate_mounts = [
            m for m in rt.fs.all_mounts() if m == "/shared" or m.startswith("/chat/")
        ]
        for mount in candidate_mounts[:6]:
            cand = posixpath.join(mount, rel)
            try:
                await session.vfs.stat(cand)
                reroot_suggestions.append(cand)
            except OSError, grpc.aio.AioRpcError:
                continue

    # Layer 1: Check parent dir for unique unicode-normalized sibling or similar names.
    try:
        names = [n for n in await session.vfs.readdir(parent) if n]
    except FileNotFoundError:
        names = None
    if names is not None:
        if allow_alternate and target_name:
            norm_target = _normalize_unicode_text(target_name).strip()
            alt_matches = [
                n for n in names if _normalize_unicode_text(n).strip() == norm_target
            ]
            if len(alt_matches) == 1:
                return posixpath.join(parent, alt_matches[0]), ""
        similar = [
            posixpath.join(parent, s) for s in _rank_similar_names(target_name, names)
        ]
        suggestions = list(dict.fromkeys([*reroot_suggestions, *similar]))[:4]
        if suggestions:
            opts = "\n".join(f"  - {s}" for s in suggestions)
            return (
                None,
                f"Path not found: {abs_path}\nDid you mean one of these?\n{opts}",
            )
        sample = ", ".join(sorted(names)[:15])
        extra_mounts = ""
        if parent == "/home" and reroot_suggestions:
            extra_mounts = "\nAvailable mounts: " + ", ".join(rt.fs.all_mounts())
        return (
            None,
            f"Path not found: {abs_path}\nEntries in {parent}: {sample or '(empty)'}{extra_mounts}",
        )

    # Layer 2: Walk up to nearest existing parent folder.
    cur = parent
    while cur and cur != "/":
        cur = posixpath.dirname(cur)
        try:
            dir_names = sorted(n for n in await session.vfs.readdir(cur) if n)[:15]
        except OSError, grpc.aio.AioRpcError:
            continue
        hint = ""
        if reroot_suggestions:
            hint = "\nDid you mean:\n" + "\n".join(
                f"  - {s}" for s in reroot_suggestions[:3]
            )
        return (
            None,
            (
                f"Path not found: {abs_path}. Nearest existing folder is {cur} "
                f"(contains: {', '.join(dir_names) or '(empty)'}).{hint}"
            ),
        )

    mounts = ", ".join(rt.fs.all_mounts())
    hint = (
        "\nDid you mean:\n" + "\n".join(f"  - {s}" for s in reroot_suggestions[:3])
        if reroot_suggestions
        else ""
    )
    return None, f"Path not found: {abs_path}. Available mounts: {mounts}{hint}"


def _raise_friendly_mount_error(
    rt: RuntimeContext, abs_path: str, exc: OSError, *, writable_only: bool
) -> None:
    if exc.errno != errno.EOPNOTSUPP:
        raise exc
    mounts = rt.fs.writable_mounts() if writable_only else rt.fs.all_mounts()
    label = "writable storage mount" if writable_only else "storage mount"
    raise ToolException(
        f"Path {abs_path!r} is not inside a {label}. Available mounts: {', '.join(mounts)}"
    ) from exc


async def _expand_search_roots(rt: RuntimeContext, abs_path: str) -> list[str]:
    """Expand virtual parent directories ('/chat', '/user', '/') into concrete storage mounts."""
    if abs_path in ("/", "/chat", "/user"):
        await rt.fs.open()
        all_mounts = rt.fs.all_mounts()
        if abs_path == "/chat":
            chat_mounts = [m for m in all_mounts if m.startswith("/chat/")]
            if not chat_mounts:
                raise ToolException(
                    "No conversation storages (/chat/<handle>) are mounted yet. "
                    f"Available mounts: {', '.join(all_mounts)}"
                )
            return chat_mounts
        if abs_path == "/user":
            user_mounts = [m for m in all_mounts if m.startswith("/user/")]
            if not user_mounts:
                raise ToolException(
                    "No personal user storages (/user/<handle>) are mounted. "
                    f"Available mounts: {', '.join(all_mounts)}"
                )
            return user_mounts
        # '/' -> search /shared first, then /home, then others
        ordered = [m for m in ("/shared", "/home") if m in all_mounts]
        ordered.extend(m for m in all_mounts if m not in ordered)
        return ordered
    return [abs_path]


# --- Tool Handlers ---


async def _read_directory_listing(
    session: Session,
    abs_path: str,
    *,
    storage_id: str,
    node_id: str,
    offset: int | None,
    eff_limit: int,
) -> ToolResult:
    raw_names = [n for n in await session.vfs.readdir(abs_path) if n]
    dirs: list[str] = []
    files: list[str] = []
    for name in raw_names:
        child_path = posixpath.join(abs_path, name)
        try:
            is_dir = await session.vfs.is_dir(child_path)
        except OSError, grpc.aio.AioRpcError:
            is_dir = False
        if is_dir:
            dirs.append(name + "/")
        else:
            files.append(name)
    ordered = sorted(dirs) + sorted(files)
    total = len(ordered)
    start_idx = (
        max(0, (offset or 1) - 1)
        if (offset or 1) >= 1
        else max(0, total + (offset or 0))
    )
    page = ordered[start_idx : start_idx + eff_limit]
    end_idx = start_idx + len(page)
    header = f"Read directory {abs_path}, entries {start_idx + 1 if page else 0}-{end_idx} of {total}"
    body = "\n".join(page) if page else "(empty directory)"
    truncated = end_idx < total
    footer = (
        f"\n[Output truncated. Continue reading with offset: {end_idx + 1}]"
        if truncated
        else ""
    )
    return (
        f"{header}\n{body}{footer}",
        {
            "path": abs_path,
            "storage_id": storage_id,
            "node_id": node_id,
            "kind": "directory",
            "truncated": truncated,
            "next_offset": end_idx + 1 if truncated else None,
            "_pre_truncated": True,
        },
    )


async def _read_blob_entry(
    rt: RuntimeContext,
    session: Session,
    abs_path: str,
    extra: NodeStatExtra,
    *,
    storage_id: str,
    node_id: str,
) -> ToolResult:
    media_cfg = rt.services.settings.media
    media_type = extra.media_type
    if media_type.startswith("image/"):
        raw_bytes = await rt.fs.read_raw_bytes(
            abs_path, max_bytes=media_cfg.max_ingest_bytes
        )
        prepared = optimize_image_bytes(raw_bytes, media_cfg)
        if isinstance(prepared, str):
            return (
                prepared,
                {
                    "path": abs_path,
                    "storage_id": storage_id,
                    "node_id": node_id,
                    "kind": "image",
                    "_pre_truncated": True,
                },
            )
        return (
            [
                {
                    "type": "text",
                    "text": f"Read image {abs_path} ({prepared.width}x{prepared.height}, {prepared.media_type})",
                },
                {"type": "image_url", "image_url": {"url": prepared.data_url}},
            ],
            {
                "path": abs_path,
                "storage_id": storage_id,
                "node_id": node_id,
                "kind": "image",
                "width": prepared.width,
                "height": prepared.height,
                "media_type": prepared.media_type,
                "_pre_truncated": True,
            },
        )

    # Non-image blob: list extracted artifact tree automatically if present.
    with contextlib.suppress(OSError, grpc.aio.AioRpcError):
        names = sorted(n for n in await session.vfs.readdir(abs_path) if n)
        if names:
            return (
                f"{abs_path} is a parsed document ({media_type}). "
                "Read its extracted artifacts underneath:\n" + "\n".join(names),
                {
                    "path": abs_path,
                    "storage_id": storage_id,
                    "node_id": node_id,
                    "kind": "blob_directory",
                    "entries": len(names),
                    "_pre_truncated": True,
                },
            )
    raise ToolException(
        f"{abs_path} is a binary file ({media_type or 'application/octet-stream'}) with no readable text or extracted artifacts."
    )


async def _read_text_file(
    rt: RuntimeContext,
    session: Session,
    abs_path: str,
    *,
    storage_id: str,
    node_id: str,
    offset: int | None,
    eff_limit: int,
) -> ToolResult:
    to_cfg = rt.services.settings.tool_output
    ft_cfg = rt.services.settings.file_tools
    media_cfg = rt.services.settings.media
    raw_data = await session.vfs.read(abs_path)
    if b"\x00" in raw_data:
        detected = detect_media_type(raw_data)
        if detected and detected.startswith("image/"):
            prepared = optimize_image_bytes(raw_data, media_cfg)
            if not isinstance(prepared, str):
                return (
                    [
                        {"type": "text", "text": f"Read image {abs_path}"},
                        {"type": "image_url", "image_url": {"url": prepared.data_url}},
                    ],
                    {"path": abs_path, "kind": "image", "_pre_truncated": True},
                )
        raise ToolException(
            f"{abs_path} appears to be a binary file containing NUL bytes."
        )

    text = raw_data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)
    note = ""
    if offset is None or offset == 0:
        start_idx = 0
    elif offset < 0:
        start_idx = max(0, total + offset)
    elif offset > total > 0:
        start_idx = max(0, total - ft_cfg.read_tail_lines)
        note = (
            f"[Note: requested offset {offset} exceeds file length ({total} lines); "
            f"showing last {total - start_idx} lines.]\n"
        )
    else:
        start_idx = offset - 1

    rendered_lines: list[str] = []
    used_bytes = 0
    idx = start_idx
    while idx < total and len(rendered_lines) < eff_limit:
        clipped = clip_line(lines[idx], to_cfg.max_line_length)
        formatted = f"{idx + 1}: {clipped}"
        b_len = len((formatted + "\n").encode("utf-8"))
        if used_bytes + b_len > to_cfg.max_bytes and rendered_lines:
            break
        rendered_lines.append(formatted)
        used_bytes += b_len
        idx += 1

    end_line = idx
    truncated = end_line < total
    header = f"Read file {abs_path}, lines {start_idx + 1 if rendered_lines else 0}-{end_line} of {total}"
    footer = (
        f"\n[Output truncated. Continue reading with offset: {end_line + 1}]"
        if truncated
        else ""
    )
    return (
        f"{header}\n{note}" + "\n".join(rendered_lines) + footer,
        {
            "path": abs_path,
            "storage_id": storage_id,
            "node_id": node_id,
            "truncated": truncated,
            "next_offset": end_line + 1 if truncated else None,
            "_pre_truncated": True,
        },
    )


async def handle_file_read(
    path: str,
    offset: int | None = None,
    limit: int | None = None,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Read a workspace text file, directory listing, image, or parsed document tree."""
    rt = runtime.context
    to_cfg = rt.services.settings.tool_output
    eff_limit = min(limit or to_cfg.max_lines, to_cfg.max_lines)

    session = await rt.fs.open()
    abs_path = normalize_workspace_path(path)
    try:
        st = await session.vfs.stat(abs_path)
    except FileNotFoundError:
        alt, err_msg = await missing_path_recovery(rt, abs_path, allow_alternate=True)
        if alt is None:
            raise ToolException(err_msg) from None
        abs_path = alt
        st = await session.vfs.stat(abs_path)

    extra = parse_stat_extra(st.extra)
    storage_id = extra.storage_id
    node_id = extra.node_id

    if st.type.value == "directory":
        return await _read_directory_listing(
            session,
            abs_path,
            storage_id=storage_id,
            node_id=node_id,
            offset=offset,
            eff_limit=eff_limit,
        )
    if extra.is_blob:
        return await _read_blob_entry(
            rt,
            session,
            abs_path,
            extra,
            storage_id=storage_id,
            node_id=node_id,
        )
    return await _read_text_file(
        rt,
        session,
        abs_path,
        storage_id=storage_id,
        node_id=node_id,
        offset=offset,
        eff_limit=eff_limit,
    )


async def handle_file_edit(
    path: str,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Edit an existing workspace text file via optimistic versioned write."""
    rt = runtime.context
    abs_path = normalize_workspace_path(path)
    ft_cfg = rt.services.settings.file_tools
    async with rt.fs.path_mutex.lock(abs_path):
        try:
            read_res = await rt.fs.read_text_with_version(abs_path)
        except FileNotFoundError:
            _, err_msg = await missing_path_recovery(
                rt, abs_path, allow_alternate=False
            )
            raise ToolException(err_msg) from None
        except OSError as exc:
            _raise_friendly_mount_error(rt, abs_path, exc, writable_only=True)
            raise
        text, version = read_res.text, read_res.version
        try:
            updated, count, diff, matched_lines, note = apply_file_edit_detailed(
                text,
                old_string,
                new_string,
                replace_all=replace_all,
                miss_hint_lines=ft_cfg.edit_miss_hint_lines,
                miss_hint_line_length=ft_cfg.edit_miss_hint_line_length,
            )
        except ValueError as exc:
            raise ToolException(str(exc)) from None
        try:
            await rt.fs.write_text_optimistic(
                abs_path,
                content=updated,
                expected_version=version,
            )
        except OSError as exc:
            _raise_friendly_mount_error(rt, abs_path, exc, writable_only=True)
            raise
        await rt.fs.notify_changed(abs_path)

    line_info = ""
    if matched_lines:
        if len(matched_lines) == 1:
            line_info = f", at line {matched_lines[0]}"
        else:
            preview = ", ".join(str(n) for n in matched_lines[:5])
            more = "…" if len(matched_lines) > 5 else ""
            line_info = f", lines {preview}{more}"
    artifact: dict[str, JSON] = {
        "path": abs_path,
        "replacements": count,
        "diff": diff[:8000],
    }
    if note:
        artifact["_note"] = note
    return (
        f"Edited {abs_path} ({count} replacement{'s' if count != 1 else ''}{line_info})",
        artifact,
    )


async def handle_file_write(
    path: str,
    content: str,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Create or overwrite a workspace text file while preserving any existing BOM."""
    rt = runtime.context
    abs_path = normalize_workspace_path(path)
    async with rt.fs.path_mutex.lock(abs_path):
        existed = False
        body = content
        try:
            old_res = await rt.fs.read_text_with_version(abs_path)
            existed = True
            if old_res.text.startswith("\ufeff") and not body.startswith("\ufeff"):
                body = "\ufeff" + body
        except FileNotFoundError:
            pass
        except OSError as exc:
            _raise_friendly_mount_error(rt, abs_path, exc, writable_only=True)
            raise
        try:
            st = await rt.fs.write_text_optimistic(abs_path, content=body)
        except OSError as exc:
            _raise_friendly_mount_error(rt, abs_path, exc, writable_only=True)
            raise
        await rt.fs.notify_changed(abs_path)
    extra = parse_stat_extra(st.extra)
    verb = "Wrote" if existed else "Created"
    line_count = len(body.splitlines())
    byte_count = len(body.encode("utf-8"))
    return (
        f"{verb} {abs_path} ({line_count} lines, {byte_count} bytes)",
        {
            "path": abs_path,
            "storage_id": extra.storage_id,
            "node_id": extra.node_id,
            "existed": existed,
        },
    )


async def handle_glob(
    pattern: str,
    path: str = "/shared",
    *,
    hidden: bool = False,
    limit: int = 100,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Find workspace files and directories matching a glob pattern."""
    rt = runtime.context
    abs_path = normalize_workspace_path(path or "/shared")
    roots = await _expand_search_roots(rt, abs_path)
    cap = min(limit, 100)
    all_hits: list[GlobHit] = []
    truncated = False

    for root in roots:
        remaining = cap - len(all_hits)
        if remaining <= 0:
            truncated = True
            break
        try:
            res = await rt.fs.glob_files(
                root,
                pattern=pattern,
                include_hidden=hidden,
                limit=remaining,
            )
        except FileNotFoundError:
            if len(roots) == 1:
                _, err_msg = await missing_path_recovery(
                    rt, root, allow_alternate=False
                )
                raise ToolException(err_msg) from None
            continue
        except OSError as exc:
            if len(roots) == 1:
                _raise_friendly_mount_error(rt, root, exc, writable_only=False)
                raise
            continue
        all_hits.extend(res.hits)
        if res.truncated:
            truncated = True

    if not all_hits:
        other = [m for m in rt.fs.all_mounts() if m != abs_path]
        extra = (
            f" (also mounted: {', '.join(other)})"
            if other and abs_path == "/shared"
            else ""
        )
        return (
            f"No files found matching {pattern!r} in {abs_path}{extra}",
            {"count": 0, "truncated": False},
        )
    lines = [f"{h.path}/" if h.kind == "directory" else h.path for h in all_hits]
    text = "\n".join(lines)
    if truncated:
        text += f"\n[Showing first {len(all_hits)} matches; refine pattern or path for more]"
    return text, {"count": len(all_hits), "truncated": truncated}


async def handle_grep(
    pattern: str,
    *,
    path: str = "/shared",
    include: str = "",
    literal: bool = False,
    case_sensitive: bool = True,
    limit: int = 100,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Search workspace file contents and extracted artifacts by regex or literal match."""
    rt = runtime.context
    if not literal:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ToolException(
                f"Invalid regex pattern {pattern!r}: {exc}. Pass literal=true for plain-text search."
            ) from None

    abs_path = normalize_workspace_path(path or "/shared")
    roots = await _expand_search_roots(rt, abs_path)
    cap = min(limit, 100)
    all_hits: list[GrepHit] = []
    truncated = False

    for root in roots:
        remaining = cap - len(all_hits)
        if remaining <= 0:
            truncated = True
            break
        try:
            res = await rt.fs.grep_files(
                root,
                pattern=pattern,
                include_glob=include,
                literal=literal,
                case_sensitive=case_sensitive,
                limit=remaining,
            )
        except FileNotFoundError:
            if len(roots) == 1:
                _, err_msg = await missing_path_recovery(
                    rt, root, allow_alternate=False
                )
                raise ToolException(err_msg) from None
            continue
        except OSError as exc:
            if len(roots) == 1:
                _raise_friendly_mount_error(rt, root, exc, writable_only=False)
                raise
            continue
        all_hits.extend(res.hits)
        if res.truncated:
            truncated = True

    if not all_hits:
        other = [m for m in rt.fs.all_mounts() if m != abs_path]
        extra = (
            f" (also mounted: {', '.join(other)})"
            if other and abs_path == "/shared"
            else ""
        )
        return (
            f"No matches found for {pattern!r} in {abs_path}{extra}",
            {"count": 0, "truncated": False},
        )
    grouped: dict[str, list[tuple[int, str]]] = {}
    for h in all_hits:
        grouped.setdefault(h.path, []).append((h.line_number, h.line_text))
    out_lines = [f"Found {len(all_hits)} match{'es' if len(all_hits) != 1 else ''}"]
    for p, entries in grouped.items():
        out_lines.append(f"{p}:")
        for ln, txt in entries:
            out_lines.append(f"  Line {ln}: {txt}")
    if truncated:
        out_lines.append(
            f"[Results truncated at {len(all_hits)} matches; narrow pattern or path]"
        )
    return "\n".join(out_lines), {"count": len(all_hits), "truncated": truncated}


async def _search_semantic_root(
    rt: RuntimeContext,
    abs_p: str,
    *,
    query: str,
    limit: int,
    baggage: str,
) -> tuple[str, list[SemanticHit] | None]:
    try:
        hits = await rt.fs.semantic_search(
            abs_p,
            query=query,
            limit=limit,
            baggage=baggage,
        )
    except FileNotFoundError:
        return abs_p, None
    except OSError as exc:
        if exc.errno == errno.EOPNOTSUPP:
            return abs_p, None
        raise
    else:
        return abs_p, hits


async def handle_semantic_search(
    query: str,
    paths: list[str] | None = None,
    limit: int = 10,
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Run hybrid vector + BM25 search across mounted workspace paths."""
    rt = runtime.context
    raw_paths = paths or ["/shared", "/home"]

    expanded: list[str] = []
    for raw_p in raw_paths[:5]:
        abs_p = normalize_workspace_path(raw_p)
        try:
            expanded.extend(await _expand_search_roots(rt, abs_p))
        except ToolException:
            if len(raw_paths) == 1:
                raise
            continue

    baggage = build_rag_baggage(
        session_id=str(rt.leta_id),
        agent_id=str(rt.agent_id),
        workspace_id=str(rt.workspace_id),
    )
    all_hits: list[SemanticHit] = []
    valid_count = 0
    missing_paths: list[str] = []
    with ExitStack() as stack:
        obs = None
        if rt.services.langfuse is not None:
            obs = stack.enter_context(
                rt.services.langfuse.start_as_current_observation(
                    name="leta.semantic_search",
                    as_type="retriever",
                    input={"query": query, "paths": raw_paths[:5], "limit": limit},
                )
            )

        capped_limit = min(limit, 25)
        results = await asyncio.gather(
            *(
                _search_semantic_root(
                    rt, abs_p, query=query, limit=capped_limit, baggage=baggage
                )
                for abs_p in expanded
            )
        )
        for abs_p, hits in results:
            if hits is None:
                missing_paths.append(abs_p)
            else:
                valid_count += 1
                all_hits.extend(hits)
        if obs is not None:
            obs.update(output={"hit_count": len(all_hits)})

    if valid_count == 0 and missing_paths:
        _, err_msg = await missing_path_recovery(
            rt, missing_paths[0], allow_alternate=False
        )
        raise ToolException(err_msg)

    all_hits.sort(key=lambda h: h.score, reverse=True)
    top = all_hits[:limit]
    if not top:
        return "No semantic matches found.", {"hits": []}
    blocks: list[str] = []
    for h in top:
        header = f"{h.path}/{h.artifact_path}" if h.artifact_path else h.path
        blocks.append(f"{header} (score={h.score:.3f}):\n{h.text}")
    return "\n\n".join(blocks), {"hits": [h.to_json() for h in top]}


async def handle_bash(
    command: str,
    workdir: str | None = None,
    timeout: int | None = None,  # noqa: ASYNC109  # Matches BashArgs.timeout field passed by StructuredTool.
    *,
    runtime: ToolRuntime[RuntimeContext, AgentState],
) -> ToolResult:
    """Execute a command in the simulated workspace shell sandbox."""
    rt = runtime.context
    resolved_wd: str | None = None
    if workdir:
        resolved_wd = normalize_workspace_path(workdir)
        session = await rt.fs.open()
        try:
            st = await session.vfs.stat(resolved_wd)
            if st.type.value != "directory":
                raise ToolException(
                    f"workdir {resolved_wd!r} is a file, not a directory."
                )
        except FileNotFoundError:
            _, err_msg = await missing_path_recovery(
                rt, resolved_wd, allow_alternate=False
            )
            raise ToolException(err_msg) from None

    res = await rt.fs.run_shell(command, workdir=resolved_wd, timeout=timeout)
    return (
        res.output or "(no output)",
        {
            "exit_code": res.exit_code,
            "wall_time_ms": res.wall_time_ms,
            "truncated": res.truncated,
            "output_path": res.output_path,
            "_pre_truncated": True,
        },
    )


# --- Tool Registration (Self-Contained OpenCode-Caliber Descriptions) ---

_FILE_READ_DESC = (
    "Read a file, directory, image, or parsed document (PDF/DOCX/XLSX/PPTX) at a workspace path "
    "('/shared', '/home', '/chat/<handle>', '/user/<handle>', or '/letfs/<storage_id>/<node_id>'). "
    "Reading a parsed blob lists its read-only extracted artifacts underneath it. "
    "Text lines are prefixed '<line>: ' (reference only; omit when editing). "
    "Prefer larger reads over tiny slices; use grep for large files."
)

_FILE_EDIT_DESC = (
    "Edit an existing file by replacing old_string with new_string. "
    "Preserve indentation and omit file_read line-number prefixes; write line breaks as \\n (existing CRLF/LF preserved). "
    "Must match uniquely unless replace_all=true. Prefer over file_write for partial edits."
)

_FILE_WRITE_DESC = (
    "Create or overwrite a text file (creates parent dirs automatically). "
    "Prefer file_edit for partial edits."
)

_GLOB_DESC = "Find files, folders, and extracted document artifacts matching a glob pattern (e.g. '**/*.csv')."

_GREP_DESC = "Search file contents and extracted artifacts by regex or literal text."

_SEMANTIC_SEARCH_DESC = "Hybrid vector + BM25 search by meaning across indexed documents and extracted artifacts."

_BASH_DESC = (
    "Run a shell command or 'python - <<\\'PY\\' ... PY' script in the simulated workspace sandbox "
    "('/home', '/shared', '/user/*', '/chat/*', '/letfs/*'). No host binaries, package installs, or native subprocesses; "
    "inspect builtins via 'help NAME' / 'man -k NAME'. Prefer dedicated file tools for simple reads/edits; "
    "use one Python script for multi-file CSV/tabular analysis. "
    "Python sandbox: 256 MB RAM, fresh interpreter, stdlib subset "
    "(annotationlib, asyncio, base64, binascii, bisect, collections, copy, csv, dataclasses, datetime, decimal, fnmatch, functools, "
    "hashlib, itertools, json, math, os, pathlib, posixpath, random, re, sys, time, tomllib, typing, unicodedata). "
    "Gotchas: '~' is not expanded in Python, omit encoding= on Path.read_text()/write_text(), sort path strings, "
    "no Path.home()/.parents/compile()/shutil/statistics, no direct network in Python (use 'curl -f' or webfetch). "
    "Large output spills to /home/.tool-output/."
)


def build_file_tools(
    *, enable_bash: bool = True, enable_semantic_search: bool = True
) -> list[BaseTool]:
    """Build file, search, and optional semantic-search/bash tools."""
    tools: list[BaseTool] = [
        make_tool(
            name="file_read",
            description=_FILE_READ_DESC,
            args_schema=FileReadArgs,
            coroutine=handle_file_read,
        ),
        make_tool(
            name="file_edit",
            description=_FILE_EDIT_DESC,
            args_schema=FileEditArgs,
            coroutine=handle_file_edit,
        ),
        make_tool(
            name="file_write",
            description=_FILE_WRITE_DESC,
            args_schema=FileWriteArgs,
            coroutine=handle_file_write,
        ),
        make_tool(
            name="glob",
            description=_GLOB_DESC,
            args_schema=GlobArgs,
            coroutine=handle_glob,
        ),
        make_tool(
            name="grep",
            description=_GREP_DESC,
            args_schema=GrepArgs,
            coroutine=handle_grep,
        ),
    ]
    if enable_semantic_search:
        tools.append(
            make_tool(
                name="semantic_search",
                description=_SEMANTIC_SEARCH_DESC,
                args_schema=SemanticSearchArgs,
                coroutine=handle_semantic_search,
            )
        )
    if enable_bash:
        tools.append(
            make_tool(
                name="bash",
                description=_BASH_DESC,
                args_schema=BashArgs,
                coroutine=handle_bash,
            )
        )
    return tools
