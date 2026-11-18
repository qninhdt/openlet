import csv
import io
import json
import re
from bisect import bisect_left
from contextlib import ExitStack
from copy import deepcopy
from itertools import accumulate
from pathlib import Path

from .layout import PARSER

TABLE_TAGS = re.compile(
    r"""<!--[\s\S]*?-->|<(/?)([a-z][\w:-]*)\b(?:[^<>"']|"[^"]*"|'[^']*')*>""",
    re.I,
)


def csv_text(rows: list[list[str]]) -> str:
    buffer = io.StringIO(newline="")
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue()


def write_rows(
    rows: list[list[str]], target: Path, max_text_bytes: int
) -> list[tuple[str, int, int]]:
    parts: list[tuple[str, int, int]] = []
    name, start = target.name, 0
    with ExitStack() as stack:
        stream = stack.enter_context(target.open("wb"))
        for index, row in enumerate(rows):
            data = csv_text([row]).encode()
            if len(data) > max_text_bytes:
                raise ValueError("table row exceeds text limit")
            if stream.tell() + len(data) > max_text_bytes:
                stream.close()
                parts.append((name, start, index))
                name = f"{target.stem}-part-{len(parts) + 1}{target.suffix}"
                start = index
                stream = stack.enter_context((target.parent / name).open("wb"))
            stream.write(data)
    parts.append((name, start, len(rows)))
    return parts


def write_html_table(markup: str, output: Path, start: int, max_text: int) -> str:
    from lxml import html

    table = html.fragment_fromstring(markup)
    # Browsers place consecutive direct rows in an implicit tbody.
    section = None
    for child in list(table):
        if child.tag != "tr":
            section = None
            continue
        if section is None:
            section = html.Element("tbody")
            child.addprevious(section)
        section.append(child)
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
    size = empty_size = len(html.tostring(shell, encoding="utf-8")) + 1
    links: list[str] = []
    chunk: list[tuple[html.HtmlElement, html.HtmlElement]] = []

    def flush() -> None:
        name = f"table-{start + 1}-part-{len(links) + 1}.md"
        (output / name).write_bytes(html.tostring(shell, encoding="utf-8") + b"\n")
        links.append(f"- [Table part {len(links) + 1}]({name})")
        for row, parent in chunk:
            parent.remove(row)
        chunk.clear()

    remaining = 0
    group_start = 0
    group_size = 0
    for index, (row, parent) in enumerate(rows):
        group_size += len(html.tostring(row, encoding="utf-8"))
        for cell in row.xpath("./th[@rowspan] | ./td[@rowspan]"):
            span = cell.get("rowspan", "").strip()
            if re.fullmatch(r"[0-9]{1,5}", span):
                remaining = max(remaining, int(span) or len(rows))
        remaining -= 1
        if remaining > 0 and index + 1 < len(rows) and parent is rows[index + 1][1]:
            continue
        remaining = 0
        if empty_size + group_size > max_text:
            raise ValueError("HTML table row group exceeds text limit")
        if size + group_size > max_text:
            flush()
            size = empty_size
        group = rows[group_start : index + 1]
        for item, destination in group:
            destination.append(item)
        chunk.extend(group)
        size += group_size
        group_start = index + 1
        group_size = 0
    if not chunk:
        raise ValueError("HTML table has no rows to split")
    flush()
    return "\n".join(links)


def externalize_tables(
    body: str, output: Path, split_tokens: int, max_text: int
) -> str:
    lines = body.splitlines(keepends=True)
    offsets = list(accumulate(map(len, lines), initial=0))
    rows: list[list[str]] | None = None
    start = end = 0
    html_end = 0
    for token in PARSER.parse(body):
        if token.map and offsets[token.map[0]] < html_end:
            continue
        if (
            token.type == "html_block"
            and token.level == 0
            and token.map
            and re.match(r"\s*<table(?=\s|>)", token.content, re.I)
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
                if len(markup.encode()) + 1 > max_text:
                    stop = bisect_left(offsets, html_end)
                    links = write_html_table(markup, output, first, max_text)
                    lines[first] = f"{links}\n\n{body[html_end : offsets[stop]]}"
                    lines[first + 1 : stop] = [""] * (stop - first - 1)
                break
        elif token.type == "table_open" and token.level == 0 and token.map:
            start, end = token.map
            rows = (
                []
                if len("".join(lines[start:end]).encode())
                > min(4 * split_tokens, max_text)
                else None
            )
        elif rows is not None and token.type == "tr_open":
            rows.append([])
        elif rows and token.type == "inline":
            rows[-1].append(token.content)
        elif rows is not None and token.type == "table_close":
            filename = f"table-{start + 1}.csv"
            parts = write_rows(rows, output / filename, max_text)
            metadata = json.dumps(
                {
                    "source": filename,
                    "parts": [part[0] for part in parts],
                    "rich": any(
                        "](" in cell or "<img" in cell for row in rows for cell in row
                    ),
                }
            )
            links = "\n".join(
                f"- [Table rows {first + 1}-{last}]({name})"
                for name, first, last in parts
            )
            lines[start] = f"<!-- artifact-table {metadata} -->\n\n{links}\n\n"
            lines[start + 1 : end] = [""] * (end - start - 1)
            rows = None
    return "".join(lines)
