"""CSV and HTML table externalization for oversized Markdown tables."""

from __future__ import annotations

import csv
import re
from bisect import bisect_left
from copy import deepcopy
from io import StringIO
from typing import TYPE_CHECKING

from markdown_it import MarkdownIt

if TYPE_CHECKING:
    from pathlib import Path

TABLE_TAGS = re.compile(r"<(/?)(table)\b[^>]*>", re.IGNORECASE)
_MD = MarkdownIt("commonmark").enable("table")


def csv_text(rows: list[list[str]]) -> str:
    """Serialize table ``rows`` as LF-delimited CSV text."""
    buffer = StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue()


def write_rows(
    rows: list[list[str]], destination: Path, max_text: int
) -> list[tuple[str, int, int]]:
    """Write rows into one or more CSV parts staying within max_text bytes per file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    header, body = (rows[:1], rows[1:]) if len(rows) > 1 else ([], rows)
    full = csv_text(rows)
    if len(full.encode("utf-8")) <= max_text:
        destination.write_text(full, encoding="utf-8")
        return [(destination.name, 0, len(rows))]

    parts: list[tuple[str, int, int]] = []
    chunk: list[list[str]] = list(header)
    first_row = len(header)
    part_num = 1
    for idx, row in enumerate(body, len(header)):
        candidate = csv_text([*chunk, row])
        if len(candidate.encode("utf-8")) > max_text and len(chunk) > len(header):
            name = f"{destination.stem}-{part_num:02d}{destination.suffix}"
            (destination.parent / name).write_text(csv_text(chunk), encoding="utf-8")
            parts.append((name, first_row, idx))
            part_num += 1
            chunk = [*header, row]
            first_row = idx
        else:
            if len(candidate.encode("utf-8")) > max_text:
                raise ValueError("table row exceeds max_text_bytes limit")
            chunk.append(row)
    if chunk:
        name = (
            destination.name
            if part_num == 1
            else f"{destination.stem}-{part_num:02d}{destination.suffix}"
        )
        (destination.parent / name).write_text(csv_text(chunk), encoding="utf-8")
        parts.append((name, first_row, len(rows)))
    return parts


def write_html_table(markup: str, output: Path, start: int, max_text: int) -> str:
    """Split an oversized HTML table into ``tables/`` files and return Markdown links."""
    from lxml import html  # noqa: PLC0415  # Optional cpu-extra dependency loaded only for oversized HTML tables.

    table = html.fragment_fromstring(markup)
    if str(table.tag).lower() != "table":
        raise ValueError("expected HTML table element")
    shell = deepcopy(table)
    rows: list[tuple[html.HtmlElement, html.HtmlElement]] = []
    for original, destination in zip(
        table.iterchildren("thead", "tbody", "tfoot"),
        shell.iterchildren("thead", "tbody", "tfoot"),
        strict=True,
    ):
        rows.extend((row, destination) for row in original.iterchildren("tr"))
        for row in list(destination.iterchildren("tr")):
            destination.remove(row)
    empty_size = len(html.tostring(shell, encoding="utf-8")) + 1
    if empty_size > max_text:
        raise ValueError("HTML table header exceeds max_text_bytes limit")
    parts: list[str] = []
    current = deepcopy(shell)
    size = empty_size
    part = 1
    out_dir = output / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)
    for row, target_section in rows:
        row_bytes = html.tostring(row, encoding="utf-8")
        if size + len(row_bytes) > max_text and size > empty_size:
            name = f"{start + 1:02d}-table-{part:02d}.html"
            (out_dir / name).write_bytes(
                html.tostring(current, encoding="utf-8") + b"\n"
            )
            parts.append(f"- [Table part {part}](tables/{name})")
            part += 1
            current = deepcopy(shell)
            size = empty_size
        dest = current.find(str(target_section.tag))
        if dest is not None:
            dest.append(deepcopy(row))
        size += len(row_bytes)
    if size > empty_size:
        name = (
            f"{start + 1:02d}-table-{part:02d}.html"
            if part > 1
            else f"{start + 1:02d}-table.html"
        )
        (out_dir / name).write_bytes(html.tostring(current, encoding="utf-8") + b"\n")
        parts.append(
            f"- [Table part {part}](tables/{name})"
            if part > 1
            else f"- [Table](tables/{name})"
        )
    return "\n".join(parts)


def externalize_tables(
    body: str, output: Path, split_tokens: int, max_text: int
) -> str:
    """Externalize oversized pipe and HTML tables to clean CSV/HTML files under tables/."""
    lines = body.splitlines(keepends=True)
    offsets: list[int] = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))

    tokens = _MD.parse(body)
    rows: list[list[str]] | None = None
    start = end = 0
    table_idx = 0
    for token in tokens:
        if (
            token.type == "html_block"
            and token.level == 0
            and token.map
            and re.match(r"\s*<table(?=\s|>)", token.content, re.IGNORECASE)
        ):
            first = token.map[0]
            depth = 0
            for match in TABLE_TAGS.finditer(body, offsets[first]):
                if (match[2] or "").lower() != "table":
                    continue
                depth += -1 if match[1] else 1
                if depth:
                    continue
                html_end = match.end()
                markup = body[offsets[first] : html_end]
                if len(markup.encode("utf-8")) + 1 > max_text:
                    stop = bisect_left(offsets, html_end)
                    links = write_html_table(markup, output, table_idx, max_text)
                    table_idx += 1
                    lines[first] = f"{links}\n\n{body[html_end : offsets[stop]]}"
                    lines[first + 1 : stop] = [""] * (stop - first - 1)
                break
        elif token.type == "table_open" and token.level == 0 and token.map:
            start, end = token.map
            raw_table = "".join(lines[start:end])
            rows = (
                []
                if len(raw_table.encode("utf-8")) > min(4 * split_tokens, max_text)
                else None
            )
        elif rows is not None and token.type == "tr_open":
            rows.append([])
        elif rows and token.type == "inline":
            rows[-1].append(token.content)
        elif rows is not None and token.type == "table_close":
            table_idx += 1
            filename = f"{table_idx:02d}-table.csv"
            parts = write_rows(rows, output / "tables" / filename, max_text)
            links = "\n".join(
                f"- [Table rows {first + 1}-{last}](tables/{name})"
                for name, first, last in parts
            )
            lines[start] = f"{links}\n"
            lines[start + 1 : end] = [""] * (end - start - 1)
            rows = None
    return "".join(lines)
