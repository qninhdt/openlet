import csv
import io
import json
import posixpath
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from markdown_it import MarkdownIt
from openlet_api.letfs.v1.internal_pb2 import ProcessingArtifact
from openlet_sdk.config import JSON

from .providers import Metadata


def artifact_paths(
    artifacts: Iterable[ProcessingArtifact], metadata: Mapping[str, Metadata]
) -> dict[str, str]:
    names: dict[str, str] = {}
    reserved: defaultdict[PurePosixPath, set[str]] = defaultdict(set)
    ordered = sorted(artifacts, key=lambda item: (item.path.count("/"), item.path))
    for item in ordered:
        path = PurePosixPath(item.path)
        if path.name == "README.md":
            name = path.name
        else:
            title = metadata[
                item.path if item.node.HasField("file") else f"{item.path}/README.md"
            ].title
            slug = re.sub(
                r"[^\w-]+", "-", unicodedata.normalize("NFKC", title).casefold()
            ).strip("-_")
            slug = (
                slug.encode("utf-8")[:160].decode("utf-8", errors="ignore").rstrip("-_")
                or "artifact"
            )
            number = (
                re.match(r"\d+-", path.name)
                if not item.node.HasField("file") or path.suffix == ".md"
                else None
            )
            name = (
                (number[0] if number else "")
                + slug
                + (path.suffix if item.node.HasField("file") else "")
            )
        names[item.path] = name
        reserved[path.parent].add(name)

    paths = {".": "."}
    used: defaultdict[PurePosixPath, set[str]] = defaultdict(set)
    next_suffix: defaultdict[tuple[PurePosixPath, str], int] = defaultdict(lambda: 2)
    for item in ordered:
        path = PurePosixPath(item.path)
        name = names[item.path]
        if name in used[path.parent]:
            suffix = path.suffix if item.node.HasField("file") else ""
            stem = name.removesuffix(suffix) if suffix else name
            key = (path.parent, name)
            number = next_suffix[key]
            while f"{stem}-{number}{suffix}" in reserved[path.parent]:
                number += 1
            next_suffix[key] = number + 1
            name = f"{stem}-{number}{suffix}"
            reserved[path.parent].add(name)
        used[path.parent].add(name)
        paths[item.path] = str(PurePosixPath(paths[str(path.parent)]) / name)
    del paths["."]
    return paths


def table_metadata(body: str) -> list[dict[str, JSON]]:
    result: list[dict[str, JSON]] = []
    rich = False
    for token in MarkdownIt("commonmark").parse(body):
        if token.type == "fence" and token.info == "csv" and rich:
            for row in csv.reader(io.StringIO(token.content, newline="")):
                for cell in row:
                    result.extend(table_metadata(cell))
        if token.type != "html_block":
            if token.type not in {"paragraph_open", "paragraph_close"}:
                rich = False
            continue
        rich = False
        match = re.fullmatch(r"<!-- artifact-table (\{[^\n]+\}) -->\s*", token.content)
        if match:
            try:
                value: JSON = json.loads(match[1])
            except ValueError:
                continue
            if isinstance(value, dict):
                result.append(value)
                rich = bool(value.get("rich"))
    return result


def rich_csv_paths(contents: Mapping[str, str]) -> set[str]:
    pending = [path for path in contents if path.endswith(".md")]
    found: set[str] = set()
    while pending:
        path = pending.pop()
        bodies = (
            (
                cell
                for row in csv.reader(io.StringIO(contents[path], newline=""))
                for cell in row
            )
            if path.endswith(".csv")
            else [contents[path]]
        )
        for body in bodies:
            for table in table_metadata(body):
                names = table.get("parts")
                if not table.get("rich") or not isinstance(names, list):
                    continue
                for name in names:
                    if not isinstance(name, str):
                        continue
                    target = posixpath.normpath(
                        posixpath.join(posixpath.dirname(path), name)
                    )
                    if target in contents and target not in found:
                        found.add(target)
                        pending.append(target)
    return found


def rewrite_artifact_links(
    body: str, old_path: str, paths: Mapping[str, str], *, csv_cells: bool = False
) -> str:
    def destination(raw: str) -> str:
        angled = raw.startswith("<")
        target = urlsplit(raw[1:-1] if angled else raw)
        if (
            target.scheme
            or target.netloc
            or not target.path
            or target.path.startswith("/")
        ):
            return raw
        resolved = posixpath.normpath(
            posixpath.join(posixpath.dirname(old_path), unquote(target.path))
        )
        if resolved not in paths:
            return raw
        relative = posixpath.relpath(
            paths[resolved], posixpath.dirname(paths[old_path]) or "."
        )
        url = urlunsplit(
            ("", "", quote(relative, safe="/-._~"), target.query, target.fragment)
        )
        return f"<{url}>" if angled else url

    def links(text: str) -> str:
        return re.sub(
            r"(?P<code>`+)(?!`)[\s\S]*?(?P=code)(?!`)|\]\((?P<target><[^>\n]+>|[^\s)]+)",
            lambda match: (
                match[0] if match["code"] else "](" + destination(match["target"])
            ),
            text,
        )

    if csv_cells:
        rows = list(csv.reader(io.StringIO(body, newline="")))
        changed = [
            [rewrite_artifact_links(cell, old_path, paths) for cell in row]
            for row in rows
        ]
        if changed == rows:
            return body
        output = io.StringIO(newline="")
        csv.writer(output).writerows(changed)
        return output.getvalue()
    lines = body.splitlines(keepends=True)
    edits: list[tuple[int, int, str]] = []
    protected: set[int] = set()
    metadata: dict[str, JSON] = {}
    for token in MarkdownIt("commonmark").parse(body):
        if token.map is None:
            continue
        start, stop = token.map
        if token.type in {"fence", "code_block"}:
            protected.update(range(start, stop))
            if token.type == "fence" and token.info == "csv" and metadata.get("rich"):
                changed = rewrite_artifact_links(
                    token.content, old_path, paths, csv_cells=True
                )
                if changed != token.content:
                    edits.append((start + 1, stop - 1, changed))
            metadata = {}
        elif token.type == "html_block":
            values = table_metadata(token.content)
            metadata = values[0] if values else {}
            if metadata:
                updated = dict(metadata)
                source = updated.get("source")
                if isinstance(source, str):
                    updated["source"] = destination(source)
                names = updated.get("parts")
                if isinstance(names, list):
                    updated["parts"] = [
                        destination(name) if isinstance(name, str) else name
                        for name in names
                    ]
                if updated != metadata:
                    edits.append(
                        (
                            start,
                            stop,
                            "<!-- artifact-table "
                            + json.dumps(updated, ensure_ascii=False)
                            + " -->\n",
                        )
                    )
        elif token.type not in {"paragraph_open", "paragraph_close"}:
            metadata = {}
    for i, line in enumerate(lines):
        if i not in protected and not any(a <= i < b for a, b, _ in edits):
            lines[i] = links(line)
    for start, stop, text in sorted(edits, reverse=True):
        lines[start:stop] = [text]
    return "".join(lines)
