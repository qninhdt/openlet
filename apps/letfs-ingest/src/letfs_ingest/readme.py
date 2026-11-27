"""README.md header stripping and artifact summary rendering."""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_BULLET_LINK_RE = re.compile(
    r"^- !?\[(.+?)\]\(([^)\s]+)\)(?:[ \t]+-[ \t]+[^\n]*)?$", re.MULTILINE
)
_DIM_SUFFIX_RE = re.compile(r" \(\d+x\d+\)")
_HEADER_PREFIX_RE = re.compile(r"^# [^\n]+\n\n> [^\n]+\n\n")
_SECTION_HEADINGS = frozenset({"## Tables", "## Images", "## Files"})
_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
_TABLE_EXTS = frozenset({".csv", ".html"})


def _single_line(text: str) -> str:
    return " ".join(text.split())


def _format_entry(path: str, title: str, description: str, *, dim: str = "") -> str:
    label = f"{_single_line(title)}{dim}"
    desc = _single_line(description)
    if desc:
        return f"- [{label}]({path}) - {desc}"
    return f"- [{label}]({path})"


def _child_group(path: str) -> str:
    ext = posixpath.splitext(path)[1].lower()
    if path.startswith("tables/") or ext in _TABLE_EXTS:
        return "Tables"
    if path.startswith("images/") or ext in _IMAGE_EXTS:
        return "Images"
    return "Files"


def _render_extra_sections(
    child_meta: Mapping[str, tuple[str, str]],
    exclude: set[str] | None = None,
) -> list[str]:
    skip = exclude or set()
    groups: dict[str, list[str]] = {"Tables": [], "Images": [], "Files": []}
    for path in sorted(child_meta):
        if path in skip:
            continue
        title, desc = child_meta[path]
        groups[_child_group(path)].append(_format_entry(path, title, desc))
    sections: list[str] = []
    for name in ("Tables", "Images", "Files"):
        entries = groups[name]
        if entries:
            sections.append(f"## {name}\n\n" + "\n".join(entries))
    return sections


def own_body(text: str) -> str:
    """Strip generated README header (# Title / > Description / attachment sections / ---)."""
    match = _HEADER_PREFIX_RE.match(text)
    if not match:
        return text
    rest = text[match.end() :]
    if rest.startswith(("## Sections\n", "## Sheet:")):
        return rest
    lines = rest.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line == "---":
            return "\n".join(lines[idx + 1 :]).lstrip("\n")
        if line == "" or line in _SECTION_HEADINGS or _BULLET_LINK_RE.fullmatch(line):
            idx += 1
            continue
        return text
    return text


def render(
    title: str,
    description: str,
    child_meta: Mapping[str, tuple[str, str]],
    body: str,
) -> str:
    """Render root README.md with Markdown title, description, and linked artifact summaries."""
    clean = own_body(body).lstrip("\n")
    header = f"# {_single_line(title)}\n\n> {_single_line(description)}"

    is_sections_index = clean.startswith(("# Document Sections\n", "## Sections\n"))
    is_workbook_index = clean.startswith(("# Workbook Index\n", "## Sheet:"))

    if is_sections_index or is_workbook_index:
        if clean.startswith("# Document Sections\n"):
            index_body = clean[len("# Document Sections\n") :].strip()
            index_body = f"## Sections\n\n{index_body}" if index_body else ""
        elif clean.startswith("# Workbook Index\n"):
            index_body = clean[len("# Workbook Index\n") :].strip()
        else:
            index_body = clean.strip()

        linked: set[str] = set()

        def replace_bullet(match: re.Match[str]) -> str:
            old_label, href = match.groups()
            norm = posixpath.normpath(href.strip("<>"))
            meta = child_meta.get(norm)
            if meta is None:
                return match.group(0)
            linked.add(norm)
            dim_match = _DIM_SUFFIX_RE.search(old_label)
            dim = dim_match.group(0) if dim_match else ""
            return _format_entry(href, meta[0], meta[1], dim=dim)

        index_body = _BULLET_LINK_RE.sub(replace_bullet, index_body)
        extras = _render_extra_sections(child_meta, exclude=linked)
        parts = [header]
        if index_body:
            parts.append(index_body)
        parts.extend(extras)
        return "\n\n".join(parts) + "\n"

    extras = _render_extra_sections(child_meta)
    parts = [header, *extras]
    if clean:
        parts.append(f"---\n\n{clean.rstrip()}")
    return "\n\n".join(parts) + "\n"
