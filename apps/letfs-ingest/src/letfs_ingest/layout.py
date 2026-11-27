"""Markdown block splitting, heading context propagation, and TOC generation."""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

import tiktoken
from markdown_it import MarkdownIt

if TYPE_CHECKING:
    from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s*(.*)$")
ENCODER = tiktoken.get_encoding("cl100k_base")
_MD = MarkdownIt("commonmark").enable("table")


def blocks(content: str) -> list[str]:
    """Split Markdown into top-level indivisible blocks, keeping slide markers attached."""
    text = content.strip()
    if not text:
        return []
    lines = text.splitlines(keepends=True)
    tokens = _MD.parse(text)
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.map is not None:
            start, end = token.map
            ranges.append((start, end))
            if token.nesting == 1:
                depth = 1
                index += 1
                while index < len(tokens) and depth > 0:
                    depth += tokens[index].nesting
                    index += 1
                continue
        index += 1
    units: list[str] = []
    for pos, (start, end) in enumerate(ranges):
        part = "".join(lines[start:end]).rstrip("\n")
        if pos == 0 and start > 0:
            prefix = "".join(lines[:start]).rstrip("\n")
            if prefix:
                part = f"{prefix}\n{part}"
        if part.strip():
            units.append(part)
    if not units:
        return [text]
    # Keep slide marker HTML comment attached to its following slide block.
    merged: list[str] = []
    i = 0
    while i < len(units):
        if re.fullmatch(r"<!--\s*slide\b[^>]*-->", units[i].strip()) and i + 1 < len(
            units
        ):
            merged.append(f"{units[i].strip()}\n\n{units[i + 1]}")
            i += 2
        else:
            merged.append(units[i])
            i += 1
    return merged


def contexts(units: list[str]) -> list[str]:
    """Compute cumulative Markdown heading prefixes for each block."""
    headings: list[tuple[int, str]] = []
    prefixes: list[str] = []
    for unit in units:
        stripped = unit.lstrip()
        first = stripped.splitlines()[0] if stripped else ""
        if first.startswith("<!-- slide "):
            headings.clear()
            prefixes.append("")
            for line in stripped.splitlines():
                match = HEADING.match(line.strip())
                if match and match.group(2).strip():
                    level = len(match.group(1))
                    headings = [(lvl, h) for lvl, h in headings if lvl < level]
                    headings.append(
                        (level, f"{match.group(1)} {match.group(2).strip()}")
                    )
            continue

        match = HEADING.match(first)
        if match:
            level = len(match.group(1))
            headings = [(lvl, h) for lvl, h in headings if lvl < level]
            prefixes.append(
                "\n\n".join(text for _, text in headings) + "\n\n" if headings else ""
            )
            if match.group(2).strip():
                headings.append((level, f"{match.group(1)} {match.group(2).strip()}"))
        else:
            prefixes.append(
                "\n\n".join(text for _, text in headings) + "\n\n" if headings else ""
            )
    return prefixes


def parts(content: str, split_tokens: int, max_text_bytes: int) -> list[str]:
    """Partition Markdown into token- and byte-bounded sections."""
    if split_tokens <= 0 or max_text_bytes <= 0:
        raise ValueError("split_tokens and max_text_bytes must be positive")
    units = blocks(content)
    if not units:
        return []
    prefixes = contexts(units)
    output: list[str] = []
    cur: list[str] = []
    cur_prefix = ""
    cur_tokens = 0
    unit_tokens_list = [len(ENCODER.encode(u)) for u in units]
    slide_span_tokens = list(unit_tokens_list)
    for i in range(len(units)):
        if units[i].lstrip().startswith("<!-- slide "):
            total = unit_tokens_list[i]
            for j in range(i + 1, len(units)):
                if units[j].lstrip().startswith("<!-- slide "):
                    break
                total += unit_tokens_list[j]
            slide_span_tokens[i] = total

    for i, (unit, raw_prefix) in enumerate(zip(units, prefixes, strict=True)):
        prefix = raw_prefix
        is_slide = unit.lstrip().startswith("<!-- slide ")
        rendered_single = f"{prefix}{unit}" if prefix and unit not in prefix else unit
        if len(rendered_single.encode("utf-8")) > max_text_bytes:
            if len(unit.encode("utf-8")) > max_text_bytes:
                raise ValueError("artifact text exceeds max_text_bytes limit")
            prefix = ""
        unit_tokens = unit_tokens_list[i]
        if not cur:
            cur = [unit]
            cur_prefix = prefix
            cur_tokens = len(ENCODER.encode(cur_prefix)) + unit_tokens
            continue
        candidate_body = "\n\n".join([*cur, unit])
        candidate = f"{cur_prefix}{candidate_body}"
        needed_tokens = slide_span_tokens[i] if is_slide else unit_tokens
        if cur_tokens + needed_tokens > split_tokens or (
            len(candidate.encode("utf-8")) > max_text_bytes
        ):
            output.append(f"{cur_prefix}" + "\n\n".join(cur))
            cur = [unit]
            cur_prefix = prefix
            cur_tokens = len(ENCODER.encode(cur_prefix)) + unit_tokens
        else:
            cur.append(unit)
            cur_tokens += unit_tokens
    if cur:
        output.append(f"{cur_prefix}" + "\n\n".join(cur))
    if len(output) == 1:
        return [content.strip() + "\n"]
    return [part.rstrip() + "\n" for part in output]


def _first_heading(text: str) -> str | None:
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln or (ln.startswith("<!--") and ln.endswith("-->")):
            continue
        match = HEADING.match(ln)
        if match:
            cleaned = match.group(2).strip()
            if cleaned and not re.fullmatch(
                r"Slide\s+\d+", cleaned, flags=re.IGNORECASE
            ):
                return cleaned[:80]
    return None


def _part_label(text: str, idx: int, repeated_titles: set[str] | None = None) -> str:
    skip = repeated_titles or set()
    lines = [
        ln.strip()
        for ln in text.splitlines()
        if ln.strip()
        and not (ln.strip().startswith("<!--") and ln.strip().endswith("-->"))
    ]
    headings: list[str] = []
    for ln in lines:
        match = HEADING.match(ln)
        if match:
            cleaned = match.group(2).strip()
            if cleaned and not re.fullmatch(
                r"Slide\s+\d+", cleaned, flags=re.IGNORECASE
            ):
                headings.append(cleaned[:80])
    for heading in headings:
        if heading not in skip:
            return heading
    if headings:
        return headings[0]
    for ln in lines:
        cleaned = ln.lstrip("# ").strip()
        if cleaned and not re.fullmatch(r"Slide\s+\d+", cleaned, flags=re.IGNORECASE):
            return cleaned[:80]
    return (lines[0].lstrip("# ").strip() if lines else "")[:80] or f"Part {idx}"


def write_markdown(
    content: str, output: Path, split_tokens: int, max_text_bytes: int
) -> list[str]:
    """Write README.md (and 01-part.md, 02-part.md, ... when split). Returns child part filenames."""
    output.mkdir(parents=True, exist_ok=True)
    sections = parts(content, split_tokens, max_text_bytes)
    if len(sections) <= 1:
        text = sections[0] if sections else content.strip() + "\n"
        (output / "README.md").write_text(text, encoding="utf-8")
        return []
    heading_counts = Counter(
        h for text in sections if (h := _first_heading(text)) is not None
    )
    repeated = {h for h, count in heading_counts.items() if count >= 2}
    width = max(2, len(str(len(sections))))
    part_names: list[str] = []
    toc_lines: list[str] = ["# Document Sections\n"]
    for idx, text in enumerate(sections, 1):
        name = f"{idx:0{width}d}-part.md"
        (output / name).write_text(text, encoding="utf-8")
        part_names.append(name)
        toc_lines.append(f"- [{_part_label(text, idx, repeated)}]({name})")
    toc = "\n".join(toc_lines) + "\n"
    if len(toc.encode("utf-8")) > max_text_bytes:
        toc = (
            "# Document Sections\n\n"
            + "\n".join(f"- [{n}]({n})" for n in part_names)
            + "\n"
        )
    (output / "README.md").write_text(toc, encoding="utf-8")
    return part_names
