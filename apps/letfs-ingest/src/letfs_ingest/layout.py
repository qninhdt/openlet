import logging
import re
from itertools import accumulate
from pathlib import Path

from markdown_it import MarkdownIt

PARSER = MarkdownIt("commonmark")


def estimated_tokens(text: str) -> int:
    return (len(text.encode("utf-8")) + 3) // 4


def blocks(content: str) -> list[str]:
    slides = list(re.finditer(r"^<!-- slide \d+ -->", content, re.M))
    if slides:
        cuts = sorted({0, *(match.start() for match in slides), len(content)})
        return [
            content[a:b].strip() for a, b in zip(cuts, cuts[1:]) if content[a:b].strip()
        ]
    lines = content.splitlines(keepends=True)
    boundaries = {0, len(lines)}
    depth = 0
    for token in PARSER.parse(content):
        if token.map and depth == 0:
            boundaries.add(token.map[0])
        depth += token.nesting
    cuts = sorted(boundaries)
    result: list[str] = []
    pending = ""
    for a, b in zip(cuts, cuts[1:]):
        block = "".join(lines[a:b]).strip()
        if not block:
            continue
        if re.fullmatch(r"#{1,6} [^\n]+|<!--[^\n]*-->|<a [^\n]+|Table [^\n]+", block):
            pending += block + "\n\n"
        else:
            result.append(pending + block)
            pending = ""
    if pending:
        result.append(pending.strip())
    return result


def contexts(units: list[str]) -> tuple[list[str], list[int]]:
    active: dict[int, str] = {}
    prefixes: list[str] = []
    penalties: list[int] = []
    for text in units:
        parsed = PARSER.parse(text)
        headings = [
            (int(token.tag[1:]), parsed[i + 1].content)
            for i, token in enumerate(parsed)
            if token.type == "heading_open" and parsed[i + 1].content.strip()
        ]
        slide = bool(re.match(r"<!-- slide \d+ -->", text))
        first = headings[0][0] if headings and text.startswith("#") else None
        inherited = {k: v for k, v in active.items() if first is None or k < first}
        prefix = (
            ""
            if slide
            else "\n".join("#" * k + " " + v for k, v in sorted(inherited.items()))
        )
        prefixes.append(prefix + "\n\n" if prefix else "")
        penalties.append(0 if slide else len(inherited) + (first is None))
        if slide:
            active.clear()
        else:
            for level, title in headings:
                active = {k: v for k, v in active.items() if k < level}
                active[level] = title
    return prefixes, penalties


def parts(content: str, split_tokens: int, max_text_bytes: int) -> list[str]:
    if split_tokens <= 0 or max_text_bytes <= 0:
        raise ValueError("require positive split_tokens and max_text_bytes")
    units = blocks(content)
    if not units:
        return [""]
    prefixes, penalties = contexts(units)
    lengths = list(accumulate((len(text.encode()) + 2 for text in units), initial=0))
    prefix_bytes = [len(prefix.encode()) for prefix in prefixes]
    n = len(units)
    target = 4 * split_tokens
    reserve = 0
    # The first part also needs room for navigation to the remaining parts.
    while True:
        best: list[tuple[int, int, float] | None] = [None] * (n + 1)
        cuts = [0] * (n + 1)
        best[n] = (0, 0, 0.0)
        for start in range(n - 1, -1, -1):
            navigation_bytes = reserve if start == 0 else 0
            capacity = max(1, target - navigation_bytes)
            for stop in range(start + 1, n + 1):
                size = (
                    lengths[stop]
                    - lengths[start]
                    - 1
                    + (prefix_bytes[start] if start else 0)
                )
                if size + navigation_bytes > max_text_bytes:
                    if stop == start + 1:
                        raise ValueError(
                            "artifact text exceeds limit: indivisible block"
                        )
                    break
                if size > capacity and stop > start + 1:
                    break
                tail = best[stop]
                if tail is None:
                    continue
                cost = (
                    tail[0] + 1,
                    tail[1] + (penalties[start] if start else 0),
                    tail[2] + (max(0, capacity - size) / target) ** 2,
                )
                current = best[start]
                if current is None or cost < current:
                    best[start], cuts[start] = cost, stop
        ranges: list[tuple[int, int]] = []
        start = 0
        while start < n:
            stop = cuts[start]
            if stop <= start:
                raise ValueError("artifact text exceeds limit")
            ranges.append((start, stop))
            start = stop
        navigation = (
            (
                "\n\n"
                + "\n".join(
                    f"- [Part {i + 1}](part-{i + 1:03}.md)"
                    for i in range(1, len(ranges))
                )
            )
            if len(ranges) > 1
            else ""
        )
        output = [
            (prefixes[a] if a else "")
            + "\n\n".join(units[a:b])
            + (navigation if i == 0 else "")
            + "\n"
            for i, (a, b) in enumerate(ranges)
        ]
        new_reserve = len(navigation.encode())
        if new_reserve > reserve:
            reserve = new_reserve
            continue
        for text in output:
            if len(text.encode()) > max_text_bytes:
                raise ValueError("artifact text exceeds limit")
            # shortcut: preserve oversized atomic lists/tables/slides; a structure-aware splitter is needed to divide them.
            if len(text.encode()) > target:
                logging.getLogger(__name__).warning(
                    "atomic Markdown block exceeds estimated token target: %s",
                    estimated_tokens(text),
                )
        return output


def write_markdown(
    content: str, output: Path, split_tokens: int, max_text_bytes: int
) -> None:
    for number, text in enumerate(parts(content, split_tokens, max_text_bytes), 1):
        name = "README.md" if number == 1 else f"part-{number:03}.md"
        (output / name).write_text(text, encoding="utf-8")
