"""Deterministic slugification, artifact path assignment, and link rewriting."""

from __future__ import annotations

import csv
import posixpath
import re
import unicodedata
from io import StringIO
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt

if TYPE_CHECKING:
    from collections.abc import Mapping

_MAX_NAME_BYTES = 64
_NUMBER_PREFIX = re.compile(r"^(\d+-)")
_INVALID_CHARS = re.compile(r"[^a-z0-9-]+")
_MARKDOWN_LINK = re.compile(r"(!?\[[^\]]*\])\(([^)\s]+)\)")
_MD = MarkdownIt("commonmark").enable("table")


def slugify(text: str, limit: int = _MAX_NAME_BYTES) -> str:
    """Convert ``text`` into a bounded lowercase ASCII slug."""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = _INVALID_CHARS.sub("-", ascii_text).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) > limit:
        slug = slug[:limit].rstrip("-")
    return slug or "item"


def numbered_prefix(stem: str) -> str:
    """Extract a leading ``NN-`` numeric prefix from a filename stem, if present."""
    match = _NUMBER_PREFIX.match(stem)
    return match.group(1) if match else ""


def artifact_paths(
    existing: list[str], slugs: Mapping[str, str | None]
) -> dict[str, str]:
    """Compute collision-free target virtual paths preserving parent folders, extensions, and NN- prefixes."""
    reserved: dict[str, set[str]] = {}
    for p in existing:
        parent = posixpath.dirname(p)
        reserved.setdefault(parent, set())
        if p == "README.md" or p not in slugs or not slugs[p]:
            reserved[parent].add(posixpath.basename(p))

    mapping: dict[str, str] = {}
    for p in existing:
        if p == "README.md" or not slugs.get(p):
            mapping[p] = p
            continue
        parent = posixpath.dirname(p)
        base = posixpath.basename(p)
        stem, ext = posixpath.splitext(base)
        prefix = numbered_prefix(stem)
        max_stem = max(8, _MAX_NAME_BYTES - len(ext) - len(prefix))
        candidate_stem = f"{prefix}{slugify(slugs[p] or '', limit=max_stem)}"
        used = reserved.setdefault(parent, set())
        final = f"{candidate_stem}{ext}"
        counter = 2
        while final in used:
            suffix = f"-{counter}"
            trimmed = candidate_stem[
                : max(1, _MAX_NAME_BYTES - len(ext) - len(suffix))
            ].rstrip("-")
            final = f"{trimmed}{suffix}{ext}"
            counter += 1
        used.add(final)
        mapping[p] = posixpath.join(parent, final) if parent else final
    return mapping


def rich_csv_paths(contents: Mapping[str, str]) -> set[str]:
    """Return CSV paths referenced via markdown links anywhere in the artifact bundle."""
    targets: set[str] = set()
    for path, body in contents.items():
        if not path.endswith(".md"):
            continue
        base = posixpath.dirname(path)
        for match in _MARKDOWN_LINK.finditer(body):
            href = match.group(2).strip("<>")
            resolved = posixpath.normpath(posixpath.join(base, href))
            if resolved.endswith(".csv"):
                targets.add(resolved)
    return targets


def _resolve_rel(base_dir: str, href: str, mapping: Mapping[str, str]) -> str:
    clean = href.strip("<>")
    if clean.startswith(("http://", "https://", "#", "mailto:", "data:")):
        return href
    old_abs = (
        posixpath.normpath(posixpath.join(base_dir, clean))
        if base_dir
        else posixpath.normpath(clean)
    )
    new_abs = mapping.get(old_abs)
    if new_abs is None or new_abs == old_abs:
        return href
    return posixpath.relpath(new_abs, base_dir or ".")


def _replace_links(text: str, base_dir: str, mapping: Mapping[str, str]) -> str:
    return _MARKDOWN_LINK.sub(
        lambda m: f"{m.group(1)}({_resolve_rel(base_dir, m.group(2), mapping)})",
        text,
    )


def _rewrite_markdown_links(
    body: str, base_dir: str, mapping: Mapping[str, str]
) -> str:
    tokens = _MD.parse(body)
    code_ranges = [
        (token.map[0], token.map[1])
        for token in tokens
        if token.type in {"fence", "code_block"} and token.map is not None
    ]

    lines = body.splitlines(keepends=True)
    out: list[str] = []
    for idx, line in enumerate(lines):
        if any(start <= idx < end for start, end in code_ranges):
            out.append(line)
            continue
        # Preserve inline code spans while rewriting markdown links.
        segments = re.split(r"(`+[^`]*`+)", line)
        for j, seg in enumerate(segments):
            if j % 2 == 1:
                continue
            segments[j] = _replace_links(seg, base_dir, mapping)
        out.append("".join(segments))
    return "".join(out)


def _rewrite_csv_links(body: str, base_dir: str, mapping: Mapping[str, str]) -> str:
    rows = list(csv.reader(StringIO(body)))
    changed = False
    for row in rows:
        for i, cell in enumerate(row):
            if "(" not in cell or "[" not in cell:
                continue
            updated = _replace_links(cell, base_dir, mapping)
            if updated != cell:
                row[i] = updated
                changed = True
    if not changed:
        return body
    buf = StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


def rewrite_artifact_links(
    content: str,
    artifact_path: str,
    media_type: str,
    mapping: Mapping[str, str],
    *,
    is_rich_csv: bool = False,
) -> str:
    """Rewrite relative artifact links inside Markdown or rich CSV content."""
    base_dir = posixpath.dirname(artifact_path)
    if media_type == "text/markdown" or artifact_path.endswith(".md"):
        return _rewrite_markdown_links(content, base_dir, mapping)
    if is_rich_csv and (media_type == "text/csv" or artifact_path.endswith(".csv")):
        return _rewrite_csv_links(content, base_dir, mapping)
    return content
