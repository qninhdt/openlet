import re
from pathlib import Path

from markdown_it import MarkdownIt

PARSER = MarkdownIt("commonmark").enable("table")


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


def contexts(units: list[str]) -> list[str]:
    active: dict[int, str] = {}
    prefixes: list[str] = []
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
        if slide:
            active.clear()
        else:
            for level, title in headings:
                active = {k: v for k, v in active.items() if k < level}
                active[level] = title
    return prefixes


def parts(content: str, split_tokens: int, max_text_bytes: int) -> list[str]:
    if split_tokens <= 0 or max_text_bytes <= 0:
        raise ValueError("require positive split_tokens and max_text_bytes")
    units = blocks(content)
    if not units:
        return [""]
    prefixes = contexts(units)
    sizes = [len(unit.encode()) for unit in units]
    target = min(4 * split_tokens, max_text_bytes)
    reserve = 0
    while True:
        output: list[str] = []
        start, used = 0, 0
        for i, size in enumerate(sizes):
            if i > start and used + 2 + size + 1 > target - (
                reserve if start == 0 else 0
            ):
                output.append(
                    (prefixes[start] if start else "") + "\n\n".join(units[start:i])
                )
                start, used = i, len(prefixes[i].encode())
            used += (2 if i > start else 0) + size
        output.append((prefixes[start] if start else "") + "\n\n".join(units[start:]))
        if len(output) > 1:
            navigation = "\n\n" + "\n".join(
                f"- [Part {i}](part-{i:03}.md)" for i in range(2, len(output) + 1)
            )
            size = len(navigation.encode())
            if size > reserve:
                reserve = size
                continue
            output[0] += navigation
        if any(len(part.encode()) + 1 > max_text_bytes for part in output):
            raise ValueError("artifact text exceeds limit")
        return [part + "\n" for part in output]


def write_markdown(
    content: str, output: Path, split_tokens: int, max_text_bytes: int
) -> None:
    for number, text in enumerate(parts(content, split_tokens, max_text_bytes), 1):
        name = "README.md" if number == 1 else f"part-{number:03}.md"
        (output / name).write_text(text, encoding="utf-8")
