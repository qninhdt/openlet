import posixpath
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from openlet_api.letfs.v1.internal_pb2 import ProcessingArtifact

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


def rewrite_artifact_links(body: str, old_path: str, paths: Mapping[str, str]) -> str:
    def destination(match: re.Match[str]) -> str:
        raw = match["target"]
        angled = raw.startswith("<")
        target = urlsplit(raw[1:-1] if angled else raw)
        if (
            target.scheme
            or target.netloc
            or not target.path
            or target.path.startswith("/")
        ):
            return match[0]
        resolved = posixpath.normpath(
            posixpath.join(posixpath.dirname(old_path), unquote(target.path))
        )
        if resolved not in paths:
            return match[0]
        relative = posixpath.relpath(
            paths[resolved], posixpath.dirname(paths[old_path]) or "."
        )
        url = urlunsplit(
            ("", "", quote(relative, safe="/-._~"), target.query, target.fragment)
        )
        return "](" + (f"<{url}>" if angled else url)

    # The exporter emits inline links/images; leave external and unknown destinations intact.
    return re.sub(r"\]\((?P<target><[^>\n]+>|[^\s)]+)", destination, body)
